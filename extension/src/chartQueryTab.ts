import { createElement, getInputValue } from "./dom"
import { timeframeLabel } from "./format"
import type { ChartQueryRecord } from "./messageProtocol"
import { askChartQuery, listChartQueries } from "./messages"
import { getSettings } from "./storage"

export type ChartQueryTabController = {
  readonly onReplayState: (replayActive: boolean) => void
}

export const queryErrorLabel = (code: string): string => {
  switch (code) {
    case "series_unregistered":
      return "등록된 봉이 없습니다 — 판단 기록 탭에서 전체 차트를 먼저 추출하세요"
    case "replay_active":
      return "리플레이 중에는 질의할 수 없습니다"
    case "hermes_timeout":
      return "트레이더 응답 시간 초과 — 다시 시도하세요"
    case "hermes_unavailable":
      return "트레이더를 호출할 수 없습니다"
    case "blocked_action_in_answer":
      return "답변이 매매지시 필터에 걸려 폐기됐습니다 — 질문을 바꿔보세요"
    case "empty_answer":
      return "빈 답변이 반환됐습니다 — 다시 시도하세요"
    default:
      return code
  }
}

export const queryItemHeading = (item: ChartQueryRecord): string => {
  const created = item.created_at_utc.slice(0, 16).replace("T", " ")
  return `${item.symbol} ${timeframeLabel(item.timeframe)} · ${created}`
}

const renderAnswer = (target: HTMLElement, item: ChartQueryRecord): void => {
  target.hidden = false
  const heading = createElement("div", "fj-query-answer-meta", queryItemHeading(item))
  const question = createElement("div", "fj-query-answer-question", item.question)
  if (item.status === "failed") {
    target.replaceChildren(
      heading,
      question,
      createElement("div", "fj-query-answer-error", queryErrorLabel(item.error_code)),
    )
    return
  }
  const body = createElement("div", "fj-query-answer-body", item.answer)
  const scope = createElement(
    "div",
    "fj-query-answer-scope",
    `근거: 등록 봉 ${item.bar_count.toLocaleString("ko-KR")}개` +
      (item.first_bar_exchange
        ? ` (${item.first_bar_exchange.slice(0, 10)} ~ ${item.last_bar_exchange.slice(0, 10)})`
        : "") +
      " · 매매지시 아님, 최종 판단은 본인 몫",
  )
  target.replaceChildren(heading, question, body, scope)
}

const chartKeys = (root: HTMLElement): { symbol: string; timeframe: string } => ({
  symbol: getInputValue(root, "providerSymbol") || getInputValue(root, "symbol"),
  timeframe: getInputValue(root, "timeframe"),
})

export const bindChartQueryTab = (root: HTMLElement): ChartQueryTabController => {
  const tabs = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-tab]"))
  const panels = Array.from(root.querySelectorAll<HTMLElement>("[data-tab-panel]"))
  const guard = root.querySelector<HTMLElement>("[data-query-guard]")
  const input = root.querySelector<HTMLTextAreaElement>("[data-query-input]")
  const submit = root.querySelector<HTMLButtonElement>("[data-query-submit]")
  const status = root.querySelector<HTMLElement>("[data-query-status]")
  const answer = root.querySelector<HTMLElement>("[data-query-answer]")
  const refreshButton = root.querySelector<HTMLButtonElement>("[data-query-refresh]")
  const list = root.querySelector<HTMLElement>("[data-query-list]")
  let replayActive = false

  const selectTab = (name: string): void => {
    root.dataset["activeTab"] = name
    for (const tab of tabs) {
      tab.setAttribute("aria-selected", tab.dataset["tab"] === name ? "true" : "false")
    }
    for (const panel of panels) {
      panel.hidden = panel.dataset["tabPanel"] !== name
    }
  }
  for (const tab of tabs) {
    tab.addEventListener("click", (event) => {
      if (event.isTrusted) {
        selectTab(tab.dataset["tab"] ?? "journal")
      }
    })
  }

  const applyReplayState = (): void => {
    if (guard !== null) {
      guard.hidden = !replayActive
    }
    if (submit !== null) {
      submit.disabled = replayActive
    }
    if (input !== null) {
      input.disabled = replayActive
    }
  }

  const setStatus = (message: string, state = "unknown"): void => {
    if (status !== null) {
      status.textContent = message
      status.dataset["csvState"] = state
    }
  }

  const renderList = (items: readonly ChartQueryRecord[]): void => {
    if (list === null) {
      return
    }
    if (items.length === 0) {
      list.replaceChildren(
        createElement("div", "fj-history-empty", "이 차트에 저장된 질의가 없습니다"),
      )
      return
    }
    list.replaceChildren(
      ...items.map((item) => {
        const entry = document.createElement("button")
        entry.type = "button"
        entry.className = "fj-history-item"
        entry.dataset["assessment"] = item.status === "answered" ? "balanced" : "failed"
        entry.append(
          createElement("span", "fj-history-instrument", queryItemHeading(item)),
          createElement("span", "fj-history-hypothesis", item.question.slice(0, 80)),
        )
        entry.addEventListener("click", (event) => {
          if (event.isTrusted && answer !== null) {
            renderAnswer(answer, item)
          }
        })
        return entry
      }),
    )
  }

  const refreshList = async (): Promise<void> => {
    const { symbol, timeframe } = chartKeys(root)
    if (!symbol || !timeframe || list === null) {
      return
    }
    try {
      const response = await listChartQueries(await getSettings(), symbol, timeframe)
      if (response.ok) {
        renderList(response.items)
      } else {
        list.replaceChildren(createElement("div", "fj-history-empty", response.error))
      }
    } catch (error) {
      list.replaceChildren(
        createElement(
          "div",
          "fj-history-empty",
          error instanceof Error ? error.message : "이력을 불러올 수 없습니다",
        ),
      )
    }
  }

  const ask = async (): Promise<void> => {
    if (replayActive || input === null || submit === null) {
      return
    }
    const question = input.value.trim()
    const { symbol, timeframe } = chartKeys(root)
    if (!question || !symbol || !timeframe) {
      setStatus("질문과 종목·타임프레임이 필요합니다", "needed")
      return
    }
    submit.disabled = true
    setStatus("전체 이력 통계 계산 + 트레이더 분석 중… (최대 3분)")
    try {
      const response = await askChartQuery(await getSettings(), symbol, timeframe, question)
      if (!response.ok) {
        setStatus(queryErrorLabel(response.error), "needed")
        return
      }
      if (response.query.status === "failed") {
        setStatus(queryErrorLabel(response.query.error_code), "needed")
        return
      }
      setStatus("답변 도착", "covered")
      input.value = ""
      if (answer !== null) {
        renderAnswer(answer, response.query)
      }
      await refreshList()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "질의 실패", "needed")
    } finally {
      submit.disabled = replayActive
    }
  }

  submit?.addEventListener("click", (event) => {
    if (event.isTrusted) {
      void ask()
    }
  })
  refreshButton?.addEventListener("click", (event) => {
    if (event.isTrusted) {
      void refreshList()
    }
  })
  applyReplayState()

  return {
    onReplayState: (next: boolean): void => {
      if (next !== replayActive) {
        replayActive = next
        applyReplayState()
      }
    },
  }
}
