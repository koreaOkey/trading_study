import { describe, expect, test } from "bun:test"

import { collectWarnings } from "../src/metadata"
import type { ConfirmedMetadata } from "../src/types"

const confirmed = (overrides: Partial<ConfirmedMetadata> = {}): ConfirmedMetadata => ({
  symbol: "005930",
  provider: "kis",
  provider_symbol: "005930",
  market_div_code: "J",
  timeframe: "1D",
  trade_date: "2026-07-09",
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
