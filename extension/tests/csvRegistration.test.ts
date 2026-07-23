import { describe, expect, test } from "bun:test"

import {
  coverageBadge,
  parseTimeframeMinutes,
  requiredCoverageEnd,
} from "../src/csvRegistration"
import type { BarSeriesCoverage } from "../src/messageProtocol"

const DECISION_TIME = "2026-07-03T12:59:59+09:00"

const coverage = (last: string): BarSeriesCoverage => ({
  symbol: "214450",
  timeframe: "240",
  bar_count: 500,
  first_time_exchange: "2024-01-02T09:00:00+09:00",
  last_time_exchange: last,
})

describe("csv coverage badge", () => {
  test("intraday timeframes parse to minutes, daily ones do not", () => {
    expect(parseTimeframeMinutes("240")).toBe(240)
    expect(parseTimeframeMinutes("15")).toBe(15)
    expect(parseTimeframeMinutes("1D")).toBeNull()
    expect(parseTimeframeMinutes("1W")).toBeNull()
  })

  test("required coverage end extends past the wall-clock horizon", () => {
    // Given: 40 x 240m bars ≈ 20 trading days; wall-clock would be under 7 days.
    const end = requiredCoverageEnd(DECISION_TIME, 240)

    // Then: the requirement accounts for session length plus weekend padding.
    expect(end).not.toBeNull()
    const days = (end!.getTime() - new Date(DECISION_TIME).getTime()) / 86_400_000
    expect(days).toBeGreaterThan(20)
  })

  test("daily timeframe never asks for a CSV", () => {
    const badge = coverageBadge("1D", DECISION_TIME, false, null)
    expect(badge.state).toBe("not-needed")
    expect(badge.registerDisabled).toBe(true)
  })

  test("unregistered chart asks for an export", () => {
    const badge = coverageBadge("240", DECISION_TIME, false, null)
    expect(badge.state).toBe("needed")
    expect(badge.registerDisabled).toBe(false)
  })

  test("coverage past the scoring window disables the register button", () => {
    const badge = coverageBadge("240", DECISION_TIME, true, coverage("2026-12-30T15:00:00+09:00"))
    expect(badge.state).toBe("covered")
    expect(badge.registerDisabled).toBe(true)
  })

  test("coverage ending before the scoring window asks for a fresh export", () => {
    const badge = coverageBadge("240", DECISION_TIME, true, coverage("2026-07-04T15:00:00+09:00"))
    expect(badge.state).toBe("needed")
    expect(badge.registerDisabled).toBe(false)
  })
})
