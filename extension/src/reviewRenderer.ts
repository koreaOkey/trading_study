import { createElement } from "./dom"
import type { DecisionReviewResult, MaCrossoverEvidence } from "./types"

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

const renderList = (title: string, items: readonly string[]): HTMLElement => {
  const section = createElement("section", "fj-review-block")
  const heading = createElement("h4", "fj-review-heading", title)
  if (items.length === 0) {
    section.replaceChildren(heading, paragraph("None identified", "fj-review-empty"))
    return section
  }
  const list = createElement("ul", "fj-review-list")
  list.replaceChildren(...items.map((item) => createElement("li", "", item)))
  section.replaceChildren(heading, list)
  return section
}

const renderTextBlock = (title: string, text: string): HTMLElement => {
  const section = createElement("section", "fj-review-block")
  section.replaceChildren(
    createElement("h4", "fj-review-heading", title),
    paragraph(text),
  )
  return section
}

const emptyReviewLists = (): readonly HTMLElement[] => [
  renderList("Sufficient evidence", []),
  renderList("Missing evidence", []),
  renderList("Excessive / redundant evidence", []),
  renderList("Contradictions", []),
]

const measurementText = (
  label: string,
  measurement: MaCrossoverEvidence["sma_50"],
): string => {
  if (measurement.value === null) {
    return `${label}: unavailable${measurement.null_reason === null ? "" : ` (${measurement.null_reason})`}`
  }
  const slope = measurement.slope_pct === null ? "slope unavailable" : `slope ${measurement.slope_pct}%`
  return `${label}: ${measurement.value}, ${slope}`
}

const thresholdLines = (evidence: MaCrossoverEvidence | null): readonly string[] => {
  const thresholds = evidence?.thresholds ?? null
  if (thresholds === null) {
    return ["Unavailable — needs at least 50 bars of evidence"]
  }
  const value = (raw: string | null): string => (raw === null ? "unavailable" : raw)
  const basisLabel =
    thresholds.basis === "cross_hold"
      ? "cross hold (keep SMA50 ≥ SMA200)"
      : "convergence hold (keep 50/200 gap narrowing)"
  const projection = thresholds.structure_projection
    .map((point) => `+${point.bar_offset}: ${point.min_close}`)
    .join(" · ")
  return [
    `Active structure: ${basisLabel}`,
    `Convergence hold — min close ${value(thresholds.convergence_min_close)}`,
    `Cross reach/hold — min close ${value(thresholds.cross_min_close)}`,
    `Stay above SMA50 — min close ${value(thresholds.sma50_hold_min_close)}`,
    `Stay above VWMA100 — min close ${value(thresholds.vwma100_hold_min_close)}`,
    ...(projection.length > 0 ? [`Structure line projection ${projection}`] : []),
    "MA arithmetic facts for the next completed bar — not trade instructions",
  ]
}

const evidenceLines = (evidence: MaCrossoverEvidence | null): readonly string[] => {
  if (evidence === null) {
    return ["Indicator evidence unavailable"]
  }
  return [
    `${evidence.provider} ${evidence.provider_symbol} · ${evidence.timeframe} · ${evidence.data_status}`,
    `Bars ${evidence.bar_count} · Close ${evidence.close ?? "unavailable"} · Volume ${evidence.volume ?? "unavailable"}`,
    measurementText("SMA50", evidence.sma_50),
    measurementText("SMA200", evidence.sma_200),
    measurementText("VWMA100", evidence.vwma_100),
    `SMA gap ${evidence.sma_50_to_sma_200_gap_pct ?? "unavailable"}% · ${evidence.gap_trend ?? "trend unavailable"}`,
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
    createElement("h3", "fj-review-title", "Review unavailable"),
    paragraph(message),
  )
  const retry = reviewRetry(root)
  if (retry !== null) {
    retry.hidden = false
  }
  revealReview(root, section, "failure")
}

export const renderReview = (root: HTMLElement, result: DecisionReviewResult): void => {
  const container = reviewContainer(root)
  const section = reviewSection(root)
  if (container === null || section === null) {
    return
  }
  section.hidden = false
  const retry = reviewRetry(root)
  if (result.status === "failed") {
    container.replaceChildren(
      createElement("h3", "fj-review-title", "Review failed"),
      renderTextBlock(
        "Overall assessment",
        `${result.failure.code}: ${result.failure.message}`,
      ),
      ...emptyReviewLists(),
      renderTextBlock("Revised decision note", "Unavailable because the review failed."),
      renderTextBlock("Risk note", "Unavailable because the review failed."),
      renderList("Structure thresholds", thresholdLines(result.evidence)),
      renderList("Evidence summary", evidenceLines(result.evidence)),
      renderTextBlock(
        "Model metadata",
        `${result.failure.review_profile} · ${result.failure.review_model}`,
      ),
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
  const summary = createElement("section", "fj-review-summary fj-review-block")
  summary.replaceChildren(
    createElement("h4", "fj-review-heading", "Overall assessment"),
    createElement("span", "fj-assessment", review.overall_assessment),
    paragraph(review.summary),
  )
  const revised = createElement("section", "fj-review-block")
  revised.replaceChildren(
    createElement("h4", "fj-review-heading", "Revised decision note"),
    paragraph(review.revised_decision_note || "No revision provided"),
  )
  const risk = createElement("section", "fj-review-block fj-review-risk")
  risk.replaceChildren(
    createElement("h4", "fj-review-heading", "Risk note"),
    paragraph(review.risk_note),
  )
  container.replaceChildren(
    createElement("h3", "fj-review-title", "Hermes decision review"),
    summary,
    renderList("Sufficient evidence", review.sufficient_evidence),
    renderList("Missing evidence", review.missing_evidence),
    renderList("Excessive / redundant evidence", review.excessive_evidence),
    renderList("Contradictions", review.contradictions),
    revised,
    risk,
    renderList("Structure thresholds", thresholdLines(result.evidence)),
    renderList("Evidence summary", evidenceLines(result.evidence)),
    renderTextBlock(
      "Model metadata",
      `${review.review_profile} · ${review.review_model} · ${review.review_created_at_utc}`,
    ),
  )
  revealReview(root, section, "complete")
}
