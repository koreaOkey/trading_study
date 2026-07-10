import { describe, expect, test } from "bun:test"

import { capturePayloadSchema, saveCaptureMessageResponseSchema } from "../src/types"

const draftPayload = {
  extracted: {
    source_url: "https://www.tradingview.com/chart/example/",
    page_title: "005930 1 Samsung Electronics",
    symbol_candidate: "005930",
    timeframe_candidate: "1D",
    decision_time_candidate: "2026-07-09T10:00:00+09:00",
    replay_active: true,
    captured_at: "2026-07-09T01:00:00.000Z",
  },
  confirmed: {
    symbol: "005930",
    provider: "kis",
    provider_symbol: "005930",
    market_div_code: "J",
    timeframe: "1D",
    decision_time_exchange: "2026-07-09T10:00:00+09:00",
    exchange_tz: "Asia/Seoul",
    price_basis: "unknown_unadjusted_assumed",
    session_state: "regular",
    provider_status: "candidate",
    scenario: "wait",
    confidence: 3,
    invalidation: "",
  },
  decision: "watch",
  notes: "test capture",
  warnings: ["provider_symbol_unconfirmed", "price_basis_unverified"],
} as const

const fullPayload = {
  ...draftPayload,
  screenshot_data_url: "data:image/png;base64,iVBORw0KGgo=",
} as const

describe("capture payload schemas", () => {
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
})
