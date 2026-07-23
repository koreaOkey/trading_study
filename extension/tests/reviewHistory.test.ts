import { describe, expect, test } from "bun:test"

import type { ReviewHistoryItem } from "../src/messageProtocol"
import { historyItemLabel } from "../src/reviewHistory"

const item = (overrides: Partial<ReviewHistoryItem> = {}): ReviewHistoryItem => ({
  capture_id: "cap-1",
  created_at: "2026-07-23T05:00:00+00:00",
  symbol: "214450",
  timeframe: "240",
  decision_time_exchange: "2026-07-03T12:59:59+09:00",
  hypothesis: "golden_cross_expected",
  decision_note: "note",
  review: null,
  ...overrides,
})

describe("review history labels", () => {
  test("pending review is labeled as such", () => {
    const label = historyItemLabel(item())
    expect(label.decision).toBe("2026-07-03 12:59")
    expect(label.hypothesis).toBe("골든크로스 예상")
    expect(label.assessment).toBe("리뷰 대기")
    expect(label.state).toBe("pending")
  })

  test("ready review surfaces the overall assessment", () => {
    const label = historyItemLabel(
      item({
        review: {
          schema_version: "decision_review_result.v1",
          capture_id: "cap-1",
          status: "ready",
          evidence: null,
          review: {
            schema_version: "decision_review.v1",
            review_created_at_utc: "2026-07-23T05:05:00Z",
            review_model: "m",
            review_profile: "trading",
            overall_assessment: "balanced",
            summary: "s",
            sufficient_evidence: [],
            missing_evidence: [],
            excessive_evidence: [],
            contradictions: [],
            revised_decision_note: "r",
            risk_note: "risk",
          },
          failure: null,
        },
      }),
    )
    expect(label.assessment).toBe("균형")
    expect(label.state).toBe("balanced")
  })

  test("failed review is labeled failed", () => {
    const label = historyItemLabel(
      item({
        review: {
          schema_version: "decision_review_result.v1",
          capture_id: "cap-1",
          status: "failed",
          evidence: null,
          review: null,
          failure: {
            code: "hermes_timeout",
            message: "timeout",
            retryable: true,
            review_model: "m",
            review_profile: "trading",
          },
        },
      }),
    )
    expect(label.assessment).toBe("실패")
    expect(label.state).toBe("failed")
  })
})
