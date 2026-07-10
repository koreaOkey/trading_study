import { setState } from "./dom"
import { buildPayload } from "./metadata"
import { checkBackendHealth, retryCapture, saveCapture } from "./messages"
import { clearRetryPayload, copyText, loadRetryPayload, storeRetryPayload } from "./retryPayload"
import { getSettings, saveDraft } from "./storage"
import type { CandidateMetadata } from "./metadata"
import type { CaptureDraftPayload, CapturePayload, Decision, WarningCode } from "./types"

export type CaptureWorkflow = {
  readonly capture: (decision: Decision) => Promise<void>
  readonly retry: () => Promise<void>
  readonly copyPayload: () => Promise<void>
  readonly saveDraftAction: () => Promise<void>
  readonly checkBackend: () => Promise<void>
}

const initialWarnings: readonly WarningCode[] = [
  "provider_symbol_unconfirmed",
  "price_basis_unverified",
]

export const createCaptureWorkflow = (
  root: HTMLElement,
  closeSheet: () => void,
  getCandidate: () => CandidateMetadata,
  refreshCandidate: () => Promise<CandidateMetadata | null>,
): CaptureWorkflow => {
  let currentDraftDecision: Decision = "watch"

  const persistRetryPayload = async (payload: CapturePayload, reason: string): Promise<void> => {
    await storeRetryPayload(payload)
    await saveDraft(root)
    setState(root, {
      status: "error",
      message: reason,
      warnings: ["backend_unavailable", "retry_exhausted"],
    })
  }

  const persistDraftStatus = async (
    reason: string,
    warnings: readonly WarningCode[],
  ): Promise<void> => {
    await saveDraft(root)
    setState(root, {
      status: "error",
      message: reason,
      warnings,
    })
  }

  const validateBeforeSave = async (payload: CaptureDraftPayload): Promise<boolean> => {
    if (payload.confirmed.symbol.length > 0 && payload.confirmed.provider_symbol.length > 0) {
      return true
    }
    await persistDraftStatus("Confirm symbol first", payload.warnings)
    return false
  }

  const completeSuccessfulCapture = async (
    id: string,
    warnings: readonly WarningCode[],
  ): Promise<void> => {
    await clearRetryPayload()
    setState(root, {
      status: "saved",
      message: `Saved ${id}`,
      warnings,
    })
    closeSheet()
  }

  const capture = async (decision: Decision): Promise<void> => {
    currentDraftDecision = decision
    setState(root, { status: "saving", message: "Capturing", warnings: [] })
    const settings = await getSettings()
    const refreshedCandidate = await refreshCandidate()
    const payload = buildPayload(root, decision, refreshedCandidate ?? getCandidate())
    if (!(await validateBeforeSave(payload))) {
      return
    }
    try {
      const response = await saveCapture(settings, payload)
      if (!response.ok) {
        if (response.retry_payload !== undefined) {
          await persistRetryPayload(response.retry_payload, response.error)
          return
        }
        await persistDraftStatus(response.error, ["backend_unavailable"])
        return
      }
      await completeSuccessfulCapture(response.id, response.warnings)
    } catch (error) {
      if (error instanceof Error) {
        await persistDraftStatus(error.message, ["backend_unavailable"])
        return
      }
      throw error
    }
  }

  const retry = async (): Promise<void> => {
    const payload = await loadRetryPayload()
    if (payload === null) {
      setState(root, {
        status: "warning",
        message: "No retry payload",
        warnings: ["backend_unavailable"],
      })
      return
    }
    setState(root, { status: "saving", message: "Retrying", warnings: [] })
    try {
      const settings = await getSettings()
      const response = await retryCapture(settings, payload)
      if (!response.ok) {
        await persistRetryPayload(response.retry_payload ?? payload, response.error)
        return
      }
      await completeSuccessfulCapture(response.id, response.warnings)
    } catch (error) {
      if (error instanceof Error) {
        await persistRetryPayload(payload, error.message)
        return
      }
      throw error
    }
  }

  const copyPayload = async (): Promise<void> => {
    const retryPayload = await loadRetryPayload()
    const payload = retryPayload ?? buildPayload(root, currentDraftDecision, getCandidate())
    await copyText(JSON.stringify(payload, null, 2))
    setState(root, {
      status: "ready",
      message: retryPayload === null ? "Draft payload copied" : "Retry payload copied",
      warnings: payload.warnings,
    })
  }

  const saveDraftAction = async (): Promise<void> => {
    const payload = buildPayload(root, currentDraftDecision, getCandidate())
    await saveDraft(root)
    setState(root, {
      status: "ready",
      message: "Draft saved",
      warnings: payload.warnings,
    })
  }

  const checkBackend = async (): Promise<void> => {
    try {
      const settings = await getSettings()
      const response = await checkBackendHealth(settings)
      setState(root, {
        status: response.ok && response.status < 500 ? "ready" : "warning",
        message: response.ok ? "Backend ready" : response.error,
        warnings: initialWarnings,
      })
    } catch (error) {
      if (error instanceof Error) {
        setState(root, {
          status: "error",
          message: "Backend unavailable",
          warnings: ["backend_unavailable"],
        })
        return
      }
      throw error
    }
  }

  return { capture, retry, copyPayload, saveDraftAction, checkBackend }
}
