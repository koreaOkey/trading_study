import { createElement, getInputValue } from "./dom"
import type { ReviewHistoryItem } from "./messageProtocol"
import { getRecentReviews } from "./messages"
import { renderReview } from "./reviewRenderer"
import { getSettings } from "./storage"

const HYPOTHESIS_LABELS: Readonly<Record<string, string>> = {
  golden_cross_expected: "Golden cross",
  dead_cross_expected: "Dead cross",
  uncertain: "Uncertain",
  long: "Long",
  short: "Short",
  watch: "Watch",
  skip: "Skip",
}

export type HistoryItemLabel = {
  readonly decision: string
  readonly hypothesis: string
  readonly assessment: string
}

export const historyItemLabel = (item: ReviewHistoryItem): HistoryItemLabel => {
  const decision = item.decision_time_exchange.slice(0, 16).replace("T", " ")
  const hypothesis = HYPOTHESIS_LABELS[item.hypothesis] ?? item.hypothesis
  const review = item.review
  const assessment =
    review === null
      ? "review pending"
      : review.status === "ready"
        ? (review.review?.overall_assessment ?? "ready")
        : "failed"
  return { decision, hypothesis, assessment }
}

export const bindReviewHistory = (root: HTMLElement): void => {
  const button = root.querySelector<HTMLButtonElement>("[data-load-history]")
  const list = root.querySelector<HTMLElement>("[data-history-list]")
  if (button === null || list === null) {
    return
  }

  const renderItems = (items: readonly ReviewHistoryItem[]): void => {
    if (items.length === 0) {
      list.replaceChildren(
        createElement("div", "fj-history-empty", "No judgments recorded for this chart yet"),
      )
      return
    }
    list.replaceChildren(
      ...items.map((item) => {
        const label = historyItemLabel(item)
        const entry = document.createElement("button")
        entry.type = "button"
        entry.className = "fj-history-item"
        entry.dataset["assessment"] = label.assessment
        entry.append(
          createElement("span", "fj-history-time", label.decision),
          createElement("span", "fj-history-hypothesis", label.hypothesis),
          createElement("span", "fj-history-assessment", label.assessment),
        )
        const review = item.review
        if (review === null) {
          entry.disabled = true
          entry.title = "Review runs when this chart's CSV is registered"
        } else {
          entry.title = item.decision_note.slice(0, 300)
          entry.addEventListener("click", (event) => {
            if (event.isTrusted) {
              renderReview(root, review)
            }
          })
        }
        return entry
      }),
    )
  }

  const load = async (): Promise<void> => {
    const symbol = getInputValue(root, "providerSymbol") || getInputValue(root, "symbol")
    const timeframe = getInputValue(root, "timeframe")
    if (!symbol || !timeframe) {
      return
    }
    button.disabled = true
    button.textContent = "Loading…"
    try {
      const response = await getRecentReviews(await getSettings(), symbol, timeframe)
      if (!response.ok) {
        list.replaceChildren(createElement("div", "fj-history-empty", response.error))
        return
      }
      renderItems(response.items)
    } catch (error) {
      list.replaceChildren(
        createElement(
          "div",
          "fj-history-empty",
          error instanceof Error ? error.message : "History unavailable",
        ),
      )
    } finally {
      button.disabled = false
      button.textContent = "Load"
    }
  }

  button.addEventListener("click", (event) => {
    if (event.isTrusted) {
      void load()
    }
  })
}
