import { describe, expect, test } from "bun:test"

import { createCaptureWorkflow } from "../src/captureWorkflow"
import type {
  ReviewCaptureMessageResponse,
  SaveCaptureMessageResponse,
} from "../src/messageProtocol"
import type {
  CaptureDraftPayload,
  DecisionReviewResult,
  ExtensionSettings,
} from "../src/types"
import type { CandidateMetadata } from "../src/metadata"

const settings: ExtensionSettings = {
  apiBaseUrl: "http://127.0.0.1:8766",
  apiToken: "",
}

const draftPayload: CaptureDraftPayload = {
  extracted: {
    source_url: "https://kr.tradingview.com/chart/example/?symbol=KRX%3A214450",
    page_title: "214450 5",
    symbol_candidate: "214450",
    timeframe_candidate: "5",
    decision_time_candidate: "2026-07-09T11:30:00+09:00",
    replay_active: true,
    captured_at: "2026-07-09T02:30:00Z",
  },
  confirmed: {
    symbol: "214450",
    provider_symbol: "214450",
    market_div_code: "J",
    timeframe: "5",
    decision_time_exchange: "2026-07-09T11:30:00+09:00",
    exchange_tz: "Asia/Seoul",
    provider_status: "candidate",
  },
  setup: "ma_crossover",
  hypothesis: "golden_cross_expected",
  decision_note: "SMA50 and SMA200 gap is narrowing.",
  warnings: ["provider_symbol_unconfirmed"],
}

const readyReview: DecisionReviewResult = {
  schema_version: "decision_review_result.v1",
  capture_id: "capture-1",
  status: "ready",
  evidence: null,
  review: {
    schema_version: "decision_review.v1",
    review_created_at_utc: "2026-07-09T02:31:00Z",
    review_model: "hermes-model",
    review_profile: "trading",
    overall_assessment: "balanced",
    summary: "Evidence is balanced.",
    sufficient_evidence: [],
    missing_evidence: [],
    excessive_evidence: [],
    contradictions: [],
    revised_decision_note: "Wait for confirmation.",
    risk_note: "Crossovers can fail.",
  },
  failure: null,
}

class FakeClassList {
  private readonly values = new Set<string>()

  add(value: string): void {
    this.values.add(value)
  }

  remove(value: string): void {
    this.values.delete(value)
  }

  contains(value: string): boolean {
    return this.values.has(value)
  }
}

class FakeRoot {
  readonly classList = new FakeClassList()
}

const makeWorkflow = (overrides: {
  readonly saveCapture?: (captureRequestId: string) => Promise<SaveCaptureMessageResponse>
  readonly reviewCapture?: (captureId: string) => Promise<ReviewCaptureMessageResponse>
  readonly onReview?: (result: DecisionReviewResult) => void
  readonly phases?: string[]
  readonly refreshCandidate?: () => Promise<CandidateMetadata | null>
  readonly onBuildCandidate?: (candidate: CandidateMetadata | undefined) => void
  readonly reviewImmediately?: () => boolean
} = {}) => {
  const root = new FakeRoot()
  let captureCalls = 0
  let reviewCalls = 0
  const workflow = createCaptureWorkflow(
    {
      root: root as HTMLElement,
      getCandidate: () => ({
        symbol: "214450",
        timeframe: "5",
        decisionTime: "2026-07-09T11:30:00+09:00",
        replayActive: true,
      }),
      refreshCandidate: overrides.refreshCandidate ?? (async () => null),
      reviewImmediately: overrides.reviewImmediately,
    },
    {
      getSettings: async () => settings,
      saveDraft: async () => undefined,
      buildPayload: (_root, candidate) => {
        overrides.onBuildCandidate?.(candidate)
        return draftPayload
      },
      saveCapture: async (_settings, _payload, captureRequestId) => {
        captureCalls += 1
        return overrides.saveCapture?.(captureRequestId) ?? {
          ok: true,
          id: "capture-1",
          warnings: [],
        }
      },
      reviewCapture: async (_settings, captureId) => {
        reviewCalls += 1
        return overrides.reviewCapture?.(captureId) ?? { ok: true, result: readyReview }
      },
      checkBackendHealth: async () => ({ ok: true, status: 200 }),
      setState: (_root, state) => overrides.phases?.push(state.message),
      setPhase: (_root, phase) => overrides.phases?.push(phase),
      clearReview: () => undefined,
      renderReview: (_root, result) => overrides.onReview?.(result),
      renderReviewError: () => undefined,
      createCaptureRequestId: () => "00000000-0000-4000-8000-000000000001",
    },
  )
  return {
    root,
    workflow,
    captureCalls: () => captureCalls,
    reviewCalls: () => reviewCalls,
  }
}

describe("submit for review workflow", () => {
  test("builds the capture payload from freshly correlated metadata", async () => {
    // Given
    const freshCandidate: CandidateMetadata = {
      symbol: "214450",
      timeframe: "15",
      decisionTime: "2026-07-09T11:45:00+09:00",
      replayActive: true,
    }
    let builtFrom: CandidateMetadata | undefined
    const harness = makeWorkflow({
      refreshCandidate: async () => freshCandidate,
      onBuildCandidate: (candidate) => {
        builtFrom = candidate
      },
    })

    // When
    await harness.workflow.submit()

    // Then
    expect(builtFrom).toEqual(freshCandidate)
  })

  test("reviews immediately when evidence is already available", async () => {
    // Given: the chart's series is registered (or the timeframe is daily).
    let rendered: DecisionReviewResult | null = null
    const harness = makeWorkflow({
      reviewImmediately: () => true,
      onReview: (result) => {
        rendered = result
      },
    })

    // When
    await harness.workflow.submit()

    // Then: the review runs right after saving instead of waiting for a CSV.
    expect(harness.reviewCalls()).toBe(1)
    expect(rendered).toEqual(readyReview)
  })

  test("saves without reviewing and defers the review to CSV registration", async () => {
    // Given
    const phases: string[] = []
    const harness = makeWorkflow({ phases })

    // When
    await harness.workflow.submit()

    // Then: the capture is saved, no review runs, and the deferred flow is announced.
    expect(harness.captureCalls()).toBe(1)
    expect(harness.reviewCalls()).toBe(0)
    expect(harness.workflow.lastCaptureId()).toBe("capture-1")
    expect(harness.root.classList.contains("fj-capture-hidden")).toBe(false)
    expect(phases.some((entry) => entry.includes("CSV registration"))).toBe(true)
  })

  test("ignores a second submit while capture is in flight", async () => {
    // Given
    let releaseCapture: (() => void) | null = null
    const capturePending = new Promise<void>((resolve) => {
      releaseCapture = resolve
    })
    const harness = makeWorkflow({
      saveCapture: async () => {
        await capturePending
        return { ok: true, id: "capture-1", warnings: [] }
      },
    })

    // When
    const first = harness.workflow.submit()
    const second = harness.workflow.submit()
    releaseCapture?.()
    await Promise.all([first, second])

    // Then
    expect(harness.captureCalls()).toBe(1)
  })

  test("retries Hermes by capture id without capturing again", async () => {
    // Given
    const harness = makeWorkflow()
    await harness.workflow.submit()

    // When
    await harness.workflow.retryReview()

    // Then
    expect(harness.captureCalls()).toBe(1)
    expect(harness.reviewCalls()).toBe(1)
  })

  test("renders a structured Hermes timeout as a recoverable review result", async () => {
    // Given
    const timeoutResult: DecisionReviewResult = {
      schema_version: "decision_review_result.v1",
      capture_id: "capture-1",
      status: "failed",
      evidence: null,
      review: null,
      failure: {
        code: "hermes_timeout",
        message: "Hermes timed out",
        retryable: true,
        review_model: "hermes-model",
        review_profile: "trading",
      },
    }
    let rendered: DecisionReviewResult | null = null
    const harness = makeWorkflow({
      reviewCapture: async () => ({ ok: true, result: timeoutResult }),
      onReview: (result) => {
        rendered = result
      },
    })

    // When
    await harness.workflow.submit()
    await harness.workflow.retryReview()

    // Then
    expect(rendered).toEqual(timeoutResult)
  })

  test("restores the overlay when the capture request throws", async () => {
    // Given
    const harness = makeWorkflow({
      saveCapture: async () => {
        throw new Error("capture failed")
      },
    })

    // When
    await harness.workflow.submit()

    // Then
    expect(harness.root.classList.contains("fj-capture-hidden")).toBe(false)
  })

  test("restores the overlay on the correlated screenshot acknowledgement", async () => {
    // Given
    let hiddenBeforeAcknowledgement = false
    let hiddenAfterAcknowledgement = true
    const harness = makeWorkflow({
      saveCapture: async (captureRequestId) => {
        hiddenBeforeAcknowledgement = harness.root.classList.contains("fj-capture-hidden")
        harness.workflow.acknowledgeScreenshot(captureRequestId)
        hiddenAfterAcknowledgement = harness.root.classList.contains("fj-capture-hidden")
        return { ok: true, id: "capture-1", warnings: [] }
      },
    })

    // When
    await harness.workflow.submit()

    // Then
    expect(hiddenBeforeAcknowledgement).toBe(true)
    expect(hiddenAfterAcknowledgement).toBe(false)
  })
})
