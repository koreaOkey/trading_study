import { describe, expect, test } from "bun:test"

import {
  collectWarnings,
  extractSymbolCandidate,
  extractTimeframeCandidate,
  formatReplayDecisionTime,
  normalizeTimeframeCandidate,
} from "../src/metadata"
import type { ConfirmedMetadata } from "../src/types"

const installTradingViewPage = (
  href: string,
  title: string,
  intervalAriaLabels: readonly string[] = [],
): void => {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { location: new URL(href) },
  })
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      title,
      querySelectorAll: () => intervalAriaLabels.map((label) => ({
        getAttribute: (name: string) => name === "aria-label" ? label : null,
        textContent: label,
      })),
    },
  })
}

const confirmed = (overrides: Partial<ConfirmedMetadata> = {}): ConfirmedMetadata => ({
  symbol: "005930",
  provider: "kis",
  provider_symbol: "005930",
  market_div_code: "J",
  timeframe: "1D",
  decision_time_exchange: "2026-07-09T10:00:00+09:00",
  exchange_tz: "Asia/Seoul",
  price_basis: "verified_adjusted",
  session_state: "regular",
  provider_status: "ready",
  scenario: "wait",
  confidence: 3,
  invalidation: "",
  ...overrides,
})

describe("TradingView candidate extraction", () => {
  test("extracts the KRX ticker from the symbol query parameter", () => {
    // Given
    installTradingViewPage(
      "https://kr.tradingview.com/chart/Lbh7g7ik/?symbol=KRX%3A214450",
      "파마리서치 319,500 ▲ +3.4%",
    )

    // When
    const symbol = extractSymbolCandidate()

    // Then
    expect(symbol).toBe("214450")
  })

  test("extracts a localized intraday interval from the fixed toolbar", () => {
    // Given
    installTradingViewPage(
      "https://kr.tradingview.com/chart/?symbol=KRX%3A214450",
      "214450 319,500 ▲ +3.4%",
      ["5 분"],
    )

    // When
    const timeframe = extractTimeframeCandidate()

    // Then
    expect(timeframe).toBe("5")
  })

  test("formats the replay epoch in the exchange timezone", () => {
    // Given
    const replayEpochSeconds = 1_783_564_200

    // When
    const decisionTime = formatReplayDecisionTime(replayEpochSeconds, "Asia/Seoul")

    // Then
    expect(decisionTime).toBe("2026-07-09T11:30:00+09:00")
  })

  test("keeps a numeric TradingView API resolution as minutes", () => {
    // Given
    const apiResolution = "5"

    // When
    const timeframe = normalizeTimeframeCandidate(apiResolution)

    // Then
    expect(timeframe).toBe("5")
  })
})

describe("collectWarnings", () => {
  test("keeps provider warning while provider status is candidate", () => {
    // Given
    const metadata = confirmed({ provider_status: "candidate" })

    // When
    const warnings = collectWarnings(metadata)

    // Then
    expect(warnings).toContain("provider_symbol_unconfirmed")
  })

  test("keeps price basis warning for unknown assumed basis", () => {
    // Given
    const metadata = confirmed({ price_basis: "unknown_unadjusted_assumed" })

    // When
    const warnings = collectWarnings(metadata)

    // Then
    expect(warnings).toContain("price_basis_unverified")
  })

  test("does not warn when provider and price metadata are confirmed", () => {
    // Given
    const metadata = confirmed()

    // When
    const warnings = collectWarnings(metadata)

    // Then
    expect(warnings).toEqual([])
  })
})
