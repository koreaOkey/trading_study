import { setState } from "./dom"
import type { OverlayState } from "./dom"
import { buildPayload } from "./metadata"
import type { CandidateMetadata } from "./metadata"
import type {
  HealthMessageResponse,
  ReviewCaptureMessageResponse,
  SaveCaptureMessageResponse,
} from "./messageProtocol"
import { checkBackendHealth, reviewCapture, saveCapture } from "./messages"
import { clearReview, renderReview, renderReviewError } from "./reviewRenderer"
import { getSettings, saveDraft } from "./storage"
import { captureDraftPayloadSchema } from "./types"
import type {
  CaptureDraftPayload,
  DecisionReviewResult,
  ExtensionSettings,
  WarningCode,
} from "./types"

export type WorkflowPhase = "idle" | "saving" | "reviewing" | "ready" | "failed"

export type CaptureWorkflow = {
  readonly submit: () => Promise<void>
  readonly retryReview: () => Promise<void>
  readonly acknowledgeScreenshot: (captureRequestId: string) => void
  readonly checkBackend: () => Promise<void>
  readonly lastCaptureId: () => string | null
}

type CaptureWorkflowOptions = {
  readonly root: HTMLElement
  readonly getCandidate: () => CandidateMetadata
  readonly refreshCandidate: () => Promise<CandidateMetadata | null>
  // Evidence already available (registered series covers this chart, or a
  // KIS-native daily timeframe) — review right after saving instead of
  // deferring to CSV registration, which would otherwise never fire.
  readonly reviewImmediately?: () => boolean
}

export type CaptureWorkflowDependencies = {
  readonly getSettings: () => Promise<ExtensionSettings>
  readonly saveDraft: (root: HTMLElement) => Promise<void>
  readonly buildPayload: (root: HTMLElement, candidate?: CandidateMetadata) => CaptureDraftPayload
  readonly saveCapture: (
    settings: ExtensionSettings,
    payload: CaptureDraftPayload,
    captureRequestId: string,
  ) => Promise<SaveCaptureMessageResponse>
  readonly reviewCapture: (
    settings: ExtensionSettings,
    captureId: string,
  ) => Promise<ReviewCaptureMessageResponse>
  readonly checkBackendHealth: (settings: ExtensionSettings) => Promise<HealthMessageResponse>
  readonly setState: (root: HTMLElement, state: OverlayState) => void
  readonly setPhase: (root: HTMLElement, phase: WorkflowPhase) => void
  readonly clearReview: (root: HTMLElement) => void
  readonly renderReview: (root: HTMLElement, result: DecisionReviewResult) => void
  readonly renderReviewError: (root: HTMLElement, message: string) => void
  readonly createCaptureRequestId: () => string
}

const initialWarnings: readonly WarningCode[] = [
  "provider_symbol_unconfirmed",
  "price_basis_unverified",
]

// After the extension is reloaded/updated, content scripts already injected in
// open tabs lose their runtime and every sendMessage throws this error.
export const describeWorkflowError = (message: string): string =>
  message.includes("Extension context invalidated")
    ? "확장이 업데이트됨 — 이 탭을 새로고침하세요"
    : message

export const setWorkflowPhase = (root: HTMLElement, phase: WorkflowPhase): void => {
  const submit = root.querySelector<HTMLButtonElement>("[data-submit-review]")
  if (submit === null) {
    return
  }
  const labels: Readonly<Record<WorkflowPhase, string>> = {
    idle: "리뷰 제출",
    saving: "캡처 저장 중…",
    reviewing: "Hermes 리뷰 중…",
    ready: "리뷰 제출",
    failed: "리뷰 제출",
  }
  submit.dataset["phase"] = phase
  submit.textContent = labels[phase]
  submit.disabled = phase === "saving" || phase === "reviewing"
}

const defaultDependencies: CaptureWorkflowDependencies = {
  getSettings,
  saveDraft,
  buildPayload,
  saveCapture,
  reviewCapture,
  checkBackendHealth,
  setState,
  setPhase: setWorkflowPhase,
  clearReview,
  renderReview,
  renderReviewError,
  createCaptureRequestId: () => crypto.randomUUID(),
}

export const createCaptureWorkflow = (
  options: CaptureWorkflowOptions,
  dependencies: CaptureWorkflowDependencies = defaultDependencies,
): CaptureWorkflow => {
  const { root } = options
  let inFlight = false
  let captureId: string | null = null
  let captureWarnings: readonly WarningCode[] = []
  let activeCaptureRequestId: string | null = null

  const acknowledgeScreenshot = (captureRequestId: string): void => {
    if (activeCaptureRequestId === captureRequestId) {
      root.classList.remove("fj-capture-hidden")
      activeCaptureRequestId = null
    }
  }

  const fail = (message: string, showReviewError: boolean): void => {
    dependencies.setPhase(root, "failed")
    dependencies.setState(root, {
      status: "error",
      message,
      warnings: captureWarnings,
    })
    if (showReviewError) {
      dependencies.renderReviewError(root, message)
    }
  }

  const runReview = async (id: string, settings: ExtensionSettings): Promise<void> => {
    dependencies.setPhase(root, "reviewing")
    dependencies.setState(root, {
      status: "saving",
      message: "Hermes 리뷰 중",
      warnings: captureWarnings,
    })
    const response = await dependencies.reviewCapture(settings, id)
    if (!response.ok) {
      fail(response.error, true)
      return
    }
    dependencies.renderReview(root, response.result)
    if (response.result.status === "ready") {
      dependencies.setPhase(root, "ready")
      dependencies.setState(root, {
        status: "saved",
        message: "리뷰 완료",
        warnings: captureWarnings,
      })
      return
    }
    fail(response.result.failure.message, false)
  }

  const submit = async (): Promise<void> => {
    if (inFlight) {
      return
    }
    inFlight = true
    captureId = null
    captureWarnings = []
    dependencies.clearReview(root)
    dependencies.setPhase(root, "saving")
    dependencies.setState(root, { status: "saving", message: "메타데이터 갱신 중", warnings: [] })
    try {
      const settings = await dependencies.getSettings()
      const refreshed = await options.refreshCandidate()
      const payload = dependencies.buildPayload(root, refreshed ?? options.getCandidate())
      const parsed = captureDraftPayloadSchema.safeParse(payload)
      if (!parsed.success) {
        await dependencies.saveDraft(root)
        fail("종목코드·타임프레임·판단 시각을 확인하세요", false)
        return
      }
      await dependencies.saveDraft(root)
      dependencies.setState(root, { status: "saving", message: "캡처 저장 중", warnings: [] })
      const captureRequestId = dependencies.createCaptureRequestId()
      activeCaptureRequestId = captureRequestId
      let response: SaveCaptureMessageResponse
      root.classList.add("fj-capture-hidden")
      try {
        response = await dependencies.saveCapture(settings, parsed.data, captureRequestId)
      } finally {
        root.classList.remove("fj-capture-hidden")
        activeCaptureRequestId = null
      }
      if (!response.ok) {
        fail(response.error, false)
        return
      }
      captureId = response.id
      captureWarnings = response.warnings
      if (options.reviewImmediately?.() === true) {
        dependencies.setState(root, {
          status: "saved",
          message: `저장됨 ${response.id}`,
          warnings: response.warnings,
        })
        await runReview(response.id, settings)
        return
      }
      dependencies.setPhase(root, "ready")
      dependencies.setState(root, {
        status: "saved",
        message: `저장됨 ${response.id} · 세션 CSV 등록 후 리뷰 실행`,
        warnings: response.warnings,
      })
    } catch (error) {
      if (error instanceof Error) {
        fail(describeWorkflowError(error.message), captureId !== null)
        return
      }
      throw error
    } finally {
      inFlight = false
    }
  }

  const retryReview = async (): Promise<void> => {
    if (inFlight || captureId === null) {
      return
    }
    inFlight = true
    try {
      await runReview(captureId, await dependencies.getSettings())
    } catch (error) {
      if (error instanceof Error) {
        fail(describeWorkflowError(error.message), true)
        return
      }
      throw error
    } finally {
      inFlight = false
    }
  }

  const checkBackend = async (): Promise<void> => {
    try {
      const response = await dependencies.checkBackendHealth(await dependencies.getSettings())
      dependencies.setState(root, {
        status: response.ok && response.status < 500 ? "ready" : "warning",
        message: response.ok ? "백엔드 연결됨" : response.error,
        warnings: initialWarnings,
      })
    } catch (error) {
      if (error instanceof Error) {
        fail(describeWorkflowError(error.message) === error.message
          ? "백엔드 연결 안 됨"
          : describeWorkflowError(error.message), false)
        return
      }
      throw error
    }
  }

  return {
    submit,
    retryReview,
    acknowledgeScreenshot,
    checkBackend,
    lastCaptureId: () => captureId,
  }
}
