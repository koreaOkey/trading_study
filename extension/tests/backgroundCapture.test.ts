import { describe, expect, test } from "bun:test"

import { attachScreenshot, failedCaptureResponse } from "../src/backgroundCapture"
import type { CaptureDraftPayload } from "../src/types"

const draftPayload: CaptureDraftPayload = {
  extracted: {
    source_url: "https://www.tradingview.com/chart/example/",
    page_title: "005930 1 Samsung Electronics",
    symbol_candidate: "005930",
    timeframe_candidate: "1D",
    captured_at: "2026-07-09T01:00:00.000Z",
  },
  confirmed: {
    symbol: "005930",
    provider: "kis",
    provider_symbol: "005930",
    market_div_code: "J",
    timeframe: "1D",
    trade_date: "2026-07-09",
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
}

describe("background capture payload handling", () => {
  test("attaches the captured screenshot to retryable payloads", () => {
    // Given
    const screenshotDataUrl = "data:image/png;base64,iVBORw0KGgo="

    // When
    const payload = attachScreenshot(draftPayload, screenshotDataUrl)

    // Then
    expect(payload.screenshot_data_url).toBe(screenshotDataUrl)
    expect(payload.confirmed.provider_symbol).toBe("005930")
  })

  test("failed capture responses preserve the full retry payload", () => {
    // Given
    const payload = attachScreenshot(draftPayload, "data:image/png;base64,iVBORw0KGgo=")

    // When
    const response = failedCaptureResponse(new Error("invalid_api_token"), payload)

    // Then
    expect(response).toEqual({
      ok: false,
      error: "invalid_api_token",
      retry_payload: payload,
    })
  })
})
