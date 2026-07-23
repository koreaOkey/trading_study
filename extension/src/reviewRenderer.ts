import { createElement } from "./dom"
import {
  assessmentLabel,
  formatDecisionTime,
  formatPercent,
  formatPrice,
  hypothesisLabel,
  timeframeLabel,
} from "./format"
import type { DecisionReviewResult, MaCrossoverEvidence } from "./types"

export type ReviewRenderContext = {
  readonly hypothesis?: string
}

const reviewContainer = (root: HTMLElement): HTMLElement | null =>
  root.querySelector<HTMLElement>("[data-review]")

const reviewSection = (root: HTMLElement): HTMLElement | null =>
  root.querySelector<HTMLElement>("[data-review-section]")

const reviewRetry = (root: HTMLElement): HTMLButtonElement | null =>
  root.querySelector<HTMLButtonElement>("[data-retry-review]")

const revealReview = (
  root: HTMLElement,
  section: HTMLElement,
  announcement: "complete" | "failure",
): void => {
  section.setAttribute("role", announcement === "failure" ? "alert" : "status")
  section.setAttribute("aria-live", announcement === "failure" ? "assertive" : "polite")
  const scroller = root.querySelector<HTMLElement>(".fj-sheet-scroll")
  if (scroller !== null) {
    scroller.scrollTop = section.offsetTop
  }
}

const paragraph = (text: string, className = "fj-review-copy"): HTMLParagraphElement =>
  createElement("p", className, text)

const bulletList = (items: readonly string[]): HTMLElement => {
  const list = createElement("ul", "fj-review-list")
  list.replaceChildren(...items.map((item) => createElement("li", "", item)))
  return list
}

const collapsible = (title: string, children: readonly HTMLElement[]): HTMLElement => {
  const details = document.createElement("details")
  details.className = "fj-review-details"
  const summary = document.createElement("summary")
  summary.textContent = title
  details.replaceChildren(summary, ...children)
  return details
}

const renderHeader = (
  evidence: MaCrossoverEvidence | null,
  hypothesis: string | undefined,
  assessment: string | null,
): HTMLElement => {
  const header = createElement("section", "fj-review-header fj-review-block")
  const chartLine =
    evidence === null
      ? "차트 정보 없음"
      : `${evidence.provider_symbol} · ${timeframeLabel(evidence.timeframe)} · ` +
        formatDecisionTime(evidence.decision_time_exchange)
  const badge = createElement(
    "span",
    "fj-assessment",
    assessment === null ? "리뷰 실패" : assessmentLabel(assessment),
  )
  badge.dataset["assessment"] = assessment ?? "failed"
  const titleRow = createElement("div", "fj-review-header-row")
  titleRow.append(createElement("h3", "fj-review-title", "판단 리뷰"), badge)
  header.append(titleRow, createElement("div", "fj-review-chart", chartLine))
  if (hypothesis !== undefined && hypothesis.length > 0) {
    header.append(
      createElement("div", "fj-review-hypothesis", `가설: ${hypothesisLabel(hypothesis)}`),
    )
  }
  return header
}

const metricRow = (label: string, value: string, note: string): HTMLElement => {
  const row = createElement("div", "fj-metric-row")
  row.append(
    createElement("span", "fj-metric-label", label),
    createElement("span", "fj-metric-value", value),
    createElement("span", "fj-metric-note", note),
  )
  return row
}

const distanceNote = (raw: string | null): string => {
  if (raw === null) {
    return ""
  }
  const value = Number.parseFloat(raw)
  if (Number.isNaN(value)) {
    return ""
  }
  const direction = value >= 0 ? "위" : "아래"
  return `종가가 ${Math.abs(value).toFixed(1)}% ${direction}`
}

const renderMetrics = (evidence: MaCrossoverEvidence | null): HTMLElement => {
  const block = createElement("section", "fj-review-block")
  block.append(createElement("h4", "fj-review-heading", "핵심 수치"))
  if (evidence === null) {
    block.append(paragraph("증거 데이터 없음", "fj-review-empty"))
    return block
  }
  const gapText =
    evidence.sma_50_to_sma_200_gap_pct === null
      ? "50/200 갭 ―"
      : `50/200 갭 ${formatPercent(evidence.sma_50_to_sma_200_gap_pct, 2)}`
  const trendText =
    evidence.gap_trend === null
      ? ""
      : { narrowing: " · 축소 중", widening: " · 확대 중", flat: " · 횡보" }[
          evidence.gap_trend
        ]
  block.append(
    metricRow("종가", formatPrice(evidence.close), ""),
    metricRow(
      "SMA50",
      formatPrice(evidence.sma_50.value),
      distanceNote(evidence.sma_50.distance_from_close_pct),
    ),
    metricRow(
      "SMA200",
      formatPrice(evidence.sma_200.value),
      distanceNote(evidence.sma_200.distance_from_close_pct),
    ),
    metricRow(
      "VWMA100",
      formatPrice(evidence.vwma_100.value),
      distanceNote(evidence.vwma_100.distance_from_close_pct),
    ),
    createElement("div", "fj-metric-gap", `${gapText}${trendText}`),
  )
  return block
}

const renderThresholds = (evidence: MaCrossoverEvidence | null): HTMLElement => {
  const block = createElement("section", "fj-review-block")
  block.append(createElement("h4", "fj-review-heading", "구조 유지 라인 (다음 봉 종가)"))
  const thresholds = evidence?.thresholds ?? null
  if (thresholds === null) {
    block.append(paragraph("계산 불가 — 봉 데이터 50개 이상 필요", "fj-review-empty"))
    return block
  }
  const crossReached = thresholds.basis === "cross_hold"
  const lines: Array<readonly [string, string | null, boolean]> = [
    ["수렴 유지", thresholds.convergence_min_close, !crossReached],
    [crossReached ? "크로스 유지" : "크로스 달성", thresholds.cross_min_close, crossReached],
    ["SMA50 위 유지", thresholds.sma50_hold_min_close, false],
    ["VWMA100 위 유지", thresholds.vwma100_hold_min_close, false],
  ]
  for (const [label, value, active] of lines) {
    const row = createElement("div", "fj-threshold-row")
    if (active) {
      row.dataset["active"] = "true"
    }
    row.append(
      createElement("span", "fj-threshold-star", active ? "★" : ""),
      createElement("span", "fj-metric-label", label),
      createElement("span", "fj-metric-value", `≥ ${formatPrice(value)}`),
    )
    block.append(row)
  }
  if (thresholds.structure_projection.length > 0) {
    const projectionText = thresholds.structure_projection
      .map((point) => `+${point.bar_offset}봉 ${formatPrice(point.min_close)}`)
      .join(" · ")
    block.append(
      collapsible("향후 5봉 투영 (경계 가정)", [
        paragraph(projectionText),
        paragraph(
          "각 값은 해당 조건이 유지되는 최소 종가이며 매매 지시가 아닙니다.",
          "fj-review-empty",
        ),
      ]),
    )
  }
  return block
}

const evidenceDetailLines = (evidence: MaCrossoverEvidence | null): readonly string[] => {
  if (evidence === null) {
    return ["증거 데이터 없음"]
  }
  return [
    `데이터: ${evidence.provider} · ${evidence.bar_count}봉 · ${evidence.data_status}`,
    `거래량(마지막 봉): ${formatPrice(evidence.volume)}`,
    ...evidence.null_reasons,
  ]
}

export const clearReview = (root: HTMLElement): void => {
  reviewContainer(root)?.replaceChildren()
  const section = reviewSection(root)
  if (section !== null) {
    section.hidden = true
    section.removeAttribute("role")
    section.setAttribute("aria-live", "polite")
  }
  const retry = reviewRetry(root)
  if (retry !== null) {
    retry.hidden = true
  }
}

export const renderReviewError = (root: HTMLElement, message: string): void => {
  const container = reviewContainer(root)
  const section = reviewSection(root)
  if (container === null || section === null) {
    return
  }
  section.hidden = false
  container.replaceChildren(
    createElement("h3", "fj-review-title", "리뷰를 불러올 수 없음"),
    paragraph(message),
  )
  const retry = reviewRetry(root)
  if (retry !== null) {
    retry.hidden = false
  }
  revealReview(root, section, "failure")
}

export const renderReview = (
  root: HTMLElement,
  result: DecisionReviewResult,
  context: ReviewRenderContext = {},
): void => {
  const container = reviewContainer(root)
  const section = reviewSection(root)
  if (container === null || section === null) {
    return
  }
  section.hidden = false
  const retry = reviewRetry(root)
  const hypothesis =
    context.hypothesis ??
    root.querySelector<HTMLInputElement>('[data-field="hypothesis"]')?.value

  if (result.status === "failed") {
    container.replaceChildren(
      renderHeader(result.evidence, hypothesis, null),
      paragraph(`${result.failure.code}: ${result.failure.message}`),
      renderMetrics(result.evidence),
      renderThresholds(result.evidence),
      collapsible("상세", [bulletList(evidenceDetailLines(result.evidence))]),
    )
    if (retry !== null) {
      retry.hidden = !result.failure.retryable
    }
    revealReview(root, section, "failure")
    return
  }
  if (retry !== null) {
    retry.hidden = true
  }
  const review = result.review

  const reviewBlock = createElement("section", "fj-review-block")
  reviewBlock.append(createElement("h4", "fj-review-heading", "리뷰"))
  reviewBlock.append(paragraph(review.summary))
  const issues: HTMLElement[] = []
  if (review.missing_evidence.length > 0) {
    issues.push(
      createElement("h5", "fj-review-subheading", "부족한 근거"),
      bulletList(review.missing_evidence),
    )
  }
  if (review.contradictions.length > 0) {
    issues.push(
      createElement("h5", "fj-review-subheading", "모순"),
      bulletList(review.contradictions),
    )
  }
  if (review.excessive_evidence.length > 0) {
    issues.push(
      createElement("h5", "fj-review-subheading", "과잉·중복 근거"),
      bulletList(review.excessive_evidence),
    )
  }
  if (issues.length === 0) {
    reviewBlock.append(paragraph("부족한 근거 없음 · 모순 없음", "fj-review-clean"))
  } else {
    reviewBlock.append(...issues)
  }
  if (review.sufficient_evidence.length > 0) {
    reviewBlock.append(
      collapsible(`충분한 근거 ${review.sufficient_evidence.length}개`, [
        bulletList(review.sufficient_evidence),
      ]),
    )
  }
  reviewBlock.append(paragraph(`⚠ ${review.risk_note}`, "fj-review-risk-line"))

  container.replaceChildren(
    renderHeader(result.evidence, hypothesis, review.overall_assessment),
    renderMetrics(result.evidence),
    renderThresholds(result.evidence),
    reviewBlock,
    collapsible("상세", [
      createElement("h5", "fj-review-subheading", "측정값 기반 수정 노트"),
      paragraph(review.revised_decision_note || "없음"),
      createElement("h5", "fj-review-subheading", "데이터 출처"),
      bulletList(evidenceDetailLines(result.evidence)),
      createElement("h5", "fj-review-subheading", "모델"),
      paragraph(
        `${review.review_profile} · ${review.review_model} · ${review.review_created_at_utc}`,
      ),
    ]),
  )
  revealReview(root, section, "complete")
}
