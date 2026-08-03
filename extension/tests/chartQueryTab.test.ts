import { describe, expect, test } from "bun:test"

import { queryErrorLabel, queryItemHeading } from "../src/chartQueryTab"
import type { ChartQueryRecord } from "../src/messageProtocol"

const record = (overrides: Partial<ChartQueryRecord>): ChartQueryRecord => ({
  query_id: "q1",
  created_at_utc: "2026-07-25T09:30:00Z",
  symbol: "214450",
  timeframe: "240",
  question: "골든크로스 이후 성적?",
  status: "answered",
  answer: "서술",
  error_code: "",
  model: "m",
  bar_count: 5384,
  first_bar_exchange: "2015-07-29T09:00:00+09:00",
  last_bar_exchange: "2026-07-24T13:00:00+09:00",
  ...overrides,
})

describe("chart query tab labels", () => {
  test("maps backend error codes to actionable Korean", () => {
    expect(queryErrorLabel("series_unregistered")).toContain("전체 차트를 먼저 추출")
    expect(queryErrorLabel("daily_history_unavailable")).toContain("KIS에서 일봉 이력")
    expect(queryErrorLabel("replay_active")).toContain("리플레이")
    expect(queryErrorLabel("unknown_code")).toBe("unknown_code")
  })

  test("heading combines symbol, timeframe, and creation time", () => {
    const heading = queryItemHeading(record({}))
    expect(heading).toContain("214450")
    expect(heading).toContain("2026-07-25 09:30")
  })
})
