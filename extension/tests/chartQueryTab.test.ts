import { describe, expect, test } from "bun:test"

import {
  mergeQueryArchive,
  queryErrorLabel,
  queryItemHeading,
  universeScopeLabel,
} from "../src/chartQueryTab"
import type { ChartQueryRecord, UniverseQueryRecord } from "../src/messageProtocol"
import {
  askUniverseQueryMessageResponseSchema,
  chartQueryRecordSchema,
  extensionMessageSchema,
} from "../src/messageProtocol"

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
  computations: [],
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

  test("universe scope labels and error code", () => {
    expect(universeScopeLabel("kr")).toBe("국장 전체")
    expect(universeScopeLabel("all")).toBe("전체 유니버스")
    expect(queryErrorLabel("universe_data_unavailable")).toContain("스캔 산출물")
  })
})

describe("universe query protocol", () => {
  const settings = { apiBaseUrl: "http://127.0.0.1:8766", apiToken: "t" }

  test("accepts ask-universe-query message and rejects bad scope", () => {
    const good = extensionMessageSchema.safeParse({
      kind: "ask-universe-query",
      settings,
      scope: "kr",
      question: "후보는?",
    })
    expect(good.success).toBe(true)
    const bad = extensionMessageSchema.safeParse({
      kind: "ask-universe-query",
      settings,
      scope: "nasdaq",
      question: "후보는?",
    })
    expect(bad.success).toBe(false)
  })

  test("parses universe query response records", () => {
    const parsed = askUniverseQueryMessageResponseSchema.parse({
      ok: true,
      query: {
        query_id: "u1",
        created_at_utc: "2026-08-05T03:00:00Z",
        scope: "all",
        question: "후보는?",
        status: "answered",
        answer: "서술",
        data_files: ["latest_kr.json"],
      },
    })
    if (!parsed.ok) {
      throw new Error("expected ok response")
    }
    expect(parsed.query.scope).toBe("all")
    expect(parsed.query.model).toBe("")
    expect(parsed.query.computations).toEqual([])
  })

  test("list-chart-queries works without symbol/timeframe (full archive)", () => {
    const parsed = extensionMessageSchema.safeParse({
      kind: "list-chart-queries",
      settings,
      limit: 200,
    })
    expect(parsed.success).toBe(true)
    const universeList = extensionMessageSchema.safeParse({
      kind: "list-universe-queries",
      settings,
      limit: 200,
    })
    expect(universeList.success).toBe(true)
  })

  test("chart records keep sandbox computations for the answer view", () => {
    const parsed = chartQueryRecordSchema.parse({
      query_id: "q1",
      created_at_utc: "2026-08-05T02:00:00Z",
      symbol: "005930",
      timeframe: "1D",
      question: "?",
      status: "answered",
      computations: [{ code: "print(1)", stdout: "1\n", stderr: "", exit_code: 0 }],
    })
    expect(parsed.computations).toEqual([{ code: "print(1)", stdout: "1\n" }])
  })
})

describe("merged query archive", () => {
  test("interleaves chart and universe queries newest first", () => {
    const chart = [
      record({ query_id: "c1", created_at_utc: "2026-08-05T01:00:00Z" }),
      record({ query_id: "c2", created_at_utc: "2026-08-05T03:00:00Z" }),
    ]
    const universe: UniverseQueryRecord[] = [
      {
        query_id: "u1",
        created_at_utc: "2026-08-05T02:00:00Z",
        scope: "kr",
        question: "후보?",
        status: "answered",
        answer: "서술",
        error_code: "",
        model: "m",
        data_files: [],
        computations: [],
      },
    ]
    const merged = mergeQueryArchive(chart, universe)
    expect(merged.map((entry) => entry.record.query_id)).toEqual(["c2", "u1", "c1"])
    expect(merged.map((entry) => entry.kind)).toEqual(["chart", "universe", "chart"])
  })
})
