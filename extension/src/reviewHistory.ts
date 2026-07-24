import { createElement, getInputValue } from "./dom"
import { assessmentLabel, hypothesisLabel, timeframeLabel } from "./format"
import type { ReviewHistoryItem } from "./messageProtocol"
import { getRecentReviews } from "./messages"
import { renderReview } from "./reviewRenderer"
import { getSettings } from "./storage"

export type HistoryItemLabel = {
  readonly instrument: string
  readonly timeframe: string
  readonly decision: string
  readonly hypothesis: string
  readonly assessment: string
  readonly state: string
}

export const historyItemLabel = (item: ReviewHistoryItem): HistoryItemLabel => {
  const instrument =
    item.symbol_name.length > 0 ? `${item.symbol_name} ${item.symbol}` : item.symbol
  const decision = item.decision_time_exchange.slice(0, 16).replace("T", " ")
  const hypothesis = hypothesisLabel(item.hypothesis)
  const review = item.review
  const state =
    review === null
      ? "pending"
      : review.status === "ready"
        ? (review.review?.overall_assessment ?? "ready")
        : "failed"
  const assessment =
    state === "pending" ? "리뷰 대기" : state === "failed" ? "실패" : assessmentLabel(state)
  return {
    instrument,
    timeframe: timeframeLabel(item.timeframe),
    decision,
    hypothesis,
    assessment,
    state,
  }
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
        createElement("div", "fj-history-empty", "이 종목에 기록된 판단이 없습니다"),
      )
      return
    }
    list.replaceChildren(
      ...items.map((item) => {
        const label = historyItemLabel(item)
        const entry = document.createElement("button")
        entry.type = "button"
        entry.className = "fj-history-item"
        entry.dataset["assessment"] = label.state
        entry.append(
          createElement("span", "fj-history-instrument", label.instrument),
          createElement("span", "fj-history-timeframe", label.timeframe),
          createElement("span", "fj-history-time", label.decision),
          createElement("span", "fj-history-hypothesis", label.hypothesis),
          createElement("span", "fj-history-assessment", label.assessment),
        )
        const review = item.review
        if (review === null) {
          entry.disabled = true
          entry.title = "CSV 등록 시 리뷰가 실행됩니다"
        } else {
          entry.title = item.decision_note.slice(0, 300)
          entry.addEventListener("click", (event) => {
            if (event.isTrusted) {
              renderReview(root, review, { hypothesis: item.hypothesis })
            }
          })
        }
        return entry
      }),
    )
  }

  const load = async (): Promise<void> => {
    const symbol = getInputValue(root, "providerSymbol") || getInputValue(root, "symbol")
    if (!symbol) {
      return
    }
    button.disabled = true
    button.textContent = "불러오는 중…"
    try {
      const response = await getRecentReviews(await getSettings(), symbol)
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
          error instanceof Error ? error.message : "목록을 불러올 수 없습니다",
        ),
      )
    } finally {
      button.disabled = false
      button.textContent = "불러오기"
    }
  }

  button.addEventListener("click", (event) => {
    if (event.isTrusted) {
      void load()
    }
  })
}
