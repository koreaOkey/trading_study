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

  // 골크 시나리오 생존선: 크로스 전엔 수렴 유지, 후엔 크로스 유지가 그 선이다.
  const activeLabel = crossReached ? "크로스 유지" : "수렴 유지"
  const activeValue = crossReached
    ? thresholds.cross_min_close
    : thresholds.convergence_min_close
  const activeRow = createElement("div", "fj-threshold-row")
  activeRow.dataset["active"] = "true"
  activeRow.append(
    createElement("span", "fj-threshold-star", "★"),
    createElement("span", "fj-metric-label", activeLabel),
    createElement("span", "fj-metric-value", `≥ ${formatPrice(activeValue)}`),
  )
  block.append(activeRow)

  const probability = thresholds.cross_probability ?? null
  if (probability !== null) {
    const probabilityLabel =
      probability.target === "reach_cross"
        ? `${probability.horizon_bars}봉 내 크로스 확률`
        : `${probability.horizon_bars}봉 유지 확률`
    block.append(
      createElement(
        "div",
        "fj-probability-line",
        `${probabilityLabel} ~${formatPercent(probability.probability_pct)} ` +
          `(최근 ${probability.return_sample_bars}봉 변동성 가정, 시뮬레이션 ${probability.paths.toLocaleString("ko-KR")}회)`,
      ),
    )
  }

  const breakout = thresholds.breakout_probability ?? null
  if (breakout !== null) {
    const parts = [
      ["SMA50", breakout.sma50_pct],
      ["SMA200", breakout.sma200_pct],
      ["VWMA100", breakout.vwma100_pct],
    ]
      .filter((entry): entry is [string, string] => entry[1] !== null)
      .map(([label, value]) => `${label} ${formatPercent(value)}`)
    const allAbove =
      breakout.all_above_pct === null
        ? ""
        : ` · 셋 다 위 ${formatPercent(breakout.all_above_pct)}`
    if (parts.length > 0) {
      block.append(
        createElement(
          "div",
          "fj-probability-line",
          `돌파 확률(${breakout.horizon_bars}봉 내 종가 ${breakout.confirm_bars}봉 연속 유지): ` +
            `${parts.join(" · ")}${allAbove}`,
        ),
      )
    }
  }

  const levelBreakout = thresholds.level_breakout_probability ?? null
  if (levelBreakout !== null) {
    block.append(
      createElement(
        "div",
        "fj-probability-line",
        `매물대 ${formatPrice(levelBreakout.level_price)} 돌파 확률` +
          `(${levelBreakout.horizon_bars}봉 내 종가 ${levelBreakout.confirm_bars}봉 연속 위): ` +
          `~${formatPercent(levelBreakout.probability_pct)} (수동 입력 레벨)`,
      ),
    )
  }

  const secondaryLines: Array<readonly [string, string | null]> = [
    [
      crossReached ? "수렴 유지" : "크로스 달성",
      crossReached ? thresholds.convergence_min_close : thresholds.cross_min_close,
    ],
    ["SMA50 위 유지", thresholds.sma50_hold_min_close],
    ["VWMA100 위 유지", thresholds.vwma100_hold_min_close],
  ]
  const secondaryRows = secondaryLines.map(([label, value]) => {
    const row = createElement("div", "fj-threshold-row")
    row.append(
      createElement("span", "fj-threshold-star", ""),
      createElement("span", "fj-metric-label", label),
      createElement("span", "fj-metric-value", `≥ ${formatPrice(value)}`),
    )
    return row
  })
  const extras: HTMLElement[] = [...secondaryRows]
  if (thresholds.structure_projection.length > 0) {
    const projectionText = thresholds.structure_projection
      .map((point) => `+${point.bar_offset}봉 ${formatPrice(point.min_close)}`)
      .join(" · ")
    extras.push(paragraph(`★ 라인 5봉 투영: ${projectionText}`))
  }
  extras.push(
    paragraph(
      "각 값은 해당 조건이 유지되는 최소 종가이며 매매 지시가 아닙니다.",
      "fj-review-empty",
    ),
  )
  block.append(collapsible("보조 라인 · 투영", extras))
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
