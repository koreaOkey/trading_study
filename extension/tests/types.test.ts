import { describe, expect, test } from "bun:test"

import {
  extensionMessageSchema,
  saveCaptureMessageResponseSchema,
} from "../src/messageProtocol"
import {
  captureDraftPayloadSchema,
  capturePayloadSchema,
  decisionReviewProfile,
  decisionReviewRiskNote,
  decisionReviewSchema,
  decisionReviewResultSchema,
} from "../src/types"
import type {
  CaptureDraftPayload,
  ConfirmedMetadata,
  Decision,
  ExtractedMetadata,
  MaCrossoverCaptureDraftPayload,
  WarningCode,
} from "../src/types"

type IsEqual<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends <Value>() => Value extends Right ? 1 : 2
    ? true
    : false

type ExpectedLegacyCaptureDraftPayload = {
  readonly extracted: ExtractedMetadata
  readonly confirmed: ConfirmedMetadata
  readonly decision: Decision
  readonly notes?: string
  readonly warnings: readonly WarningCode[]
}

type IncompleteCaptureDraftPayload = {
  readonly extracted: ExtractedMetadata
  readonly confirmed: ConfirmedMetadata
  readonly warnings: readonly WarningCode[]
}

const draftPayload = {
  extracted: {
    source_url: "https://www.tradingview.com/chart/example/",
    page_title: "005930 1 Samsung Electronics",
    symbol_candidate: "005930",
    symbol_name_candidate: "삼성전자",
    timeframe_candidate: "1D",
    decision_time_candidate: "2026-07-09T10:00:00+09:00",
    replay_active: true,
    captured_at: "2026-07-09T01:00:00.000Z",
  },
  confirmed: {
    symbol: "005930",
    provider_symbol: "005930",
    market_div_code: "J",
    timeframe: "1D",
    decision_time_exchange: "2026-07-09T10:00:00+09:00",
    exchange_tz: "Asia/Seoul",
    provider_status: "candidate",
  },
  setup: "ma_crossover",
  hypothesis: "golden_cross_expected",
  decision_note: "SMA50 is converging on SMA200 with VWMA100 support.",
  warnings: ["provider_symbol_unconfirmed"],
} as const

const fullPayload = {
  ...draftPayload,
  screenshot_data_url: "data:image/png;base64,iVBORw0KGgo=",
} as const

describe("capture payload schemas", () => {
  test("keeps the transport type as a strict new-or-legacy union", () => {
    // Given
    const isStrictUnion: IsEqual<
      CaptureDraftPayload,
      MaCrossoverCaptureDraftPayload | ExpectedLegacyCaptureDraftPayload
    > = true
    const rejectsIncompletePayload: IncompleteCaptureDraftPayload extends CaptureDraftPayload
      ? false
      : true = true

    // When
    const actual = isStrictUnion && rejectsIncompletePayload

    // Then
    expect(actual).toBe(true)
  })

  test("rejects a payload with neither the new nor legacy fields", () => {
    // Given
    const incompletePayload = {
      extracted: draftPayload.extracted,
      confirmed: draftPayload.confirmed,
      warnings: draftPayload.warnings,
    }

    // When
    const parsed = captureDraftPayloadSchema.safeParse(incompletePayload)

    // Then
    expect(parsed.success).toBe(false)
  })

  test("rejects a payload mixing new and legacy variants", () => {
    // Given
    const mixedPayload = {
      ...draftPayload,
      decision: "watch",
      notes: "legacy note",
    }

    // When
    const parsed = captureDraftPayloadSchema.safeParse(mixedPayload)

    // Then
    expect(parsed.success).toBe(false)
  })

  test("accepts a legacy decision while defaulting omitted notes", () => {
    // Given
    const legacyPayload = {
      extracted: draftPayload.extracted,
      confirmed: draftPayload.confirmed,
      decision: "watch",
      warnings: draftPayload.warnings,
    }

    // When
    const parsed = captureDraftPayloadSchema.safeParse(legacyPayload)

    // Then
    expect(parsed.success).toBe(true)
    if (parsed.success) {
      expect("notes" in parsed.data ? parsed.data.notes : undefined).toBe("")
    }
  })

  test("requires screenshot data for retry payloads", () => {
    // Given
    // When
    const draftResult = capturePayloadSchema.safeParse(draftPayload)
    const fullResult = capturePayloadSchema.safeParse(fullPayload)

    // Then
    expect(draftResult.success).toBe(false)
    expect(fullResult.success).toBe(true)
  })

  test("accepts failed save responses with full retry payload", () => {
    // Given
    const response = {
      ok: false,
      error: "invalid_api_token",
      retry_payload: fullPayload,
    }

    // When
    const parsed = saveCaptureMessageResponseSchema.parse(response)

    // Then
    expect(parsed).toEqual(response)
  })

  test("uses decision time without a separate trade date", () => {
    // Given
    const payloadWithoutTradeDate = fullPayload

    // When
    const parsed = capturePayloadSchema.safeParse(payloadWithoutTradeDate)

    // Then
    expect(parsed.success).toBe(true)
  })

  test("rejects decision time without an exchange offset", () => {
    // Given
    const payloadWithNaiveTime = {
      ...fullPayload,
      confirmed: {
        ...fullPayload.confirmed,
        decision_time_exchange: "2026-07-09T10:00:00",
      },
    }

    // When
    const parsed = capturePayloadSchema.safeParse(payloadWithNaiveTime)

    // Then
    expect(parsed.success).toBe(false)
  })

  test("rejects an unsupported MA crossover hypothesis", () => {
    // Given
    const payloadWithUnknownHypothesis = {
      ...fullPayload,
      hypothesis: "bullish_cross",
    }

    // When
    const parsed = capturePayloadSchema.safeParse(payloadWithUnknownHypothesis)

    // Then
    expect(parsed.success).toBe(false)
  })
})

describe("decision review result schema", () => {
  test("accepts a structured ready review", () => {
    // Given
    const result = {
      schema_version: "decision_review_result.v1",
      capture_id: "0123456789abcdef01234567",
      status: "ready",
      evidence: null,
      review: {
        schema_version: "decision_review.v1",
        review_created_at_utc: "2026-07-09T01:05:00Z",
        review_model: "hermes-model",
        review_profile: decisionReviewProfile,
        overall_assessment: "balanced",
        summary: "The evidence matches the stated hypothesis.",
        sufficient_evidence: ["SMA50/SMA200 gap is narrowing"],
        missing_evidence: ["Volume confirmation"],
        excessive_evidence: [],
        contradictions: [],
        revised_decision_note: "Watch for a confirmed cross with volume.",
        risk_note: decisionReviewRiskNote,
      },
      failure: null,
    }

    // When
    const parsed = decisionReviewResultSchema.safeParse(result)

    // Then
    expect(parsed.success).toBe(true)
  })

  test("rejects a ready result carrying a failure", () => {
    // Given
    const invalidResult = {
      schema_version: "decision_review_result.v1",
      capture_id: "0123456789abcdef01234567",
      status: "ready",
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

    // When
    const parsed = decisionReviewResultSchema.safeParse(invalidResult)

    // Then
    expect(parsed.success).toBe(false)
  })

  test("rejects a review using a non-trading profile", () => {
    // Given
    const invalidReview = {
      schema_version: "decision_review.v1",
      review_created_at_utc: "2026-07-09T01:05:00Z",
      review_model: "hermes-model",
      review_profile: "general",
      overall_assessment: "balanced",
      summary: "The evidence matches the stated hypothesis.",
      sufficient_evidence: [],
      missing_evidence: [],
      excessive_evidence: [],
      contradictions: [],
      revised_decision_note: "Wait for confirmation.",
      risk_note:
        "기술적 분석은 확률적 시나리오 정리이며 수익 보장이나 개인화된 투자 지시가 아니다.",
    }

    // When
    const parsed = decisionReviewSchema.safeParse(invalidReview)

    // Then
    expect(parsed.success).toBe(false)
  })

  test("rejects a review replacing the server-owned risk note", () => {
    // Given
    const invalidReview = {
      schema_version: "decision_review.v1",
      review_created_at_utc: "2026-07-09T01:05:00Z",
      review_model: "hermes-model",
      review_profile: "trading",
      overall_assessment: "balanced",
      summary: "The evidence matches the stated hypothesis.",
      sufficient_evidence: [],
      missing_evidence: [],
      excessive_evidence: [],
      contradictions: [],
      revised_decision_note: "Wait for confirmation.",
      risk_note: "This review is guaranteed to be safe.",
    }

    // When
    const parsed = decisionReviewSchema.safeParse(invalidReview)

    // Then
    expect(parsed.success).toBe(false)
  })

  test("accepts a review request containing only settings and a capture id", () => {
    // Given
    const message = {
      kind: "review-capture",
      settings: { apiBaseUrl: "http://127.0.0.1:8766", apiToken: "local-token" },
      captureId: "0123456789abcdef01234567",
    }

    // When
    const parsed = extensionMessageSchema.safeParse(message)

    // Then
    expect(parsed.success).toBe(true)
  })
})
