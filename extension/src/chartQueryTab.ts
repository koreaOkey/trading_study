import { createElement, getInputValue } from "./dom"
import { timeframeLabel } from "./format"
import type {
  ChartQueryRecord,
  QueryComputation,
  UniverseQueryRecord,
  UniverseScope,
} from "./messageProtocol"
import { universeScopeValues } from "./messageProtocol"
import {
  askChartQuery,
  askUniverseQuery,
  listAllChartQueries,
  listUniverseQueries,
} from "./messages"
import { getSettings } from "./storage"

export type QueryArchiveEntry =
  | { readonly kind: "chart"; readonly record: ChartQueryRecord }
  | { readonly kind: "universe"; readonly record: UniverseQueryRecord }

export const mergeQueryArchive = (
  chart: readonly ChartQueryRecord[],
  universe: readonly UniverseQueryRecord[],
): QueryArchiveEntry[] => {
  const entries: QueryArchiveEntry[] = [
    ...chart.map((record) => ({ kind: "chart", record }) as const),
    ...universe.map((record) => ({ kind: "universe", record }) as const),
  ]
  return entries.sort((a, b) =>
    b.record.created_at_utc.localeCompare(a.record.created_at_utc),
  )
}

export type ChartQueryTabController = {
  readonly onReplayState: (replayActive: boolean) => void
}

export const universeScopeLabel = (scope: UniverseScope): string => {
  switch (scope) {
    case "kr":
      return "국장 전체"
    case "us":
      return "미장 전체"
    case "crypto":
      return "코인 전체"
    case "all":
      return "전체 유니버스"
  }
}

export const queryErrorLabel = (code: string): string => {
  switch (code) {
    case "series_unregistered":
      return "등록된 봉이 없습니다 — 판단 기록 탭에서 전체 차트를 먼저 추출하세요"
    case "daily_history_unavailable":
      return "KIS에서 일봉 이력을 가져오지 못했습니다 — 잠시 후 다시 시도하세요"
    case "universe_data_unavailable":
      return "스캔 산출물이 없습니다 — 돈복사 스캐너가 아직 안 돌았는지 확인하세요"
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

const computationDetails = (
  computations: readonly QueryComputation[],
): HTMLElement[] =>
  computations.map((round, index) => {
    const details = document.createElement("details")
    details.className = "fj-query-comps"
    const summary = document.createElement("summary")
    summary.textContent = `계산 ${index + 1} — 실행 코드·출력`
    const code = document.createElement("pre")
    code.textContent = round.code
    const stdout = document.createElement("pre")
    stdout.textContent = round.stdout
    details.append(summary, code, stdout)
    return details
  })

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
  target.replaceChildren(heading, question, body, scope, ...computationDetails(item.computations))
}

const renderUniverseAnswer = (target: HTMLElement, item: UniverseQueryRecord): void => {
  target.hidden = false
  const created = item.created_at_utc.slice(0, 16).replace("T", " ")
  const heading = createElement(
    "div",
    "fj-query-answer-meta",
    `${universeScopeLabel(item.scope)} · ${created}`,
  )
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
    `근거: 스캔 유니버스 산출물 ${item.data_files.join(", ") || "—"}` +
      " · 매매지시 아님, 최종 판단은 본인 몫",
  )
  target.replaceChildren(heading, question, body, scope, ...computationDetails(item.computations))
}

const isUniverseScope = (value: string): value is UniverseScope =>
  (universeScopeValues as readonly string[]).includes(value)

const chartKeys = (root: HTMLElement): { symbol: string; timeframe: string } => ({
  symbol: getInputValue(root, "providerSymbol") || getInputValue(root, "symbol"),
  timeframe: getInputValue(root, "timeframe"),
})

export const bindChartQueryTab = (root: HTMLElement): ChartQueryTabController => {
  const tabs = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-tab]"))
  const panels = Array.from(root.querySelectorAll<HTMLElement>("[data-tab-panel]"))
  const guard = root.querySelector<HTMLElement>("[data-query-guard]")
  const scopeSelect = root.querySelector<HTMLSelectElement>("[data-query-scope]")
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
    if (scopeSelect !== null) {
      // 유니버스 질의도 리플레이 중엔 차단 — 오늘 스캔이 리플레이 화면에
      // 미래 정보를 흘리는 것을 막는다.
      scopeSelect.disabled = replayActive
    }
  }

  const setStatus = (message: string, state = "unknown"): void => {
    if (status !== null) {
      status.textContent = message
      status.dataset["csvState"] = state
    }
  }

  const renderList = (entries: readonly QueryArchiveEntry[]): void => {
    if (list === null) {
      return
    }
    if (entries.length === 0) {
      list.replaceChildren(
        createElement("div", "fj-history-empty", "저장된 질의가 없습니다"),
      )
      return
    }
    list.replaceChildren(
      ...entries.map((archived) => {
        const { record } = archived
        const entry = document.createElement("button")
        entry.type = "button"
        entry.className = "fj-history-item"
        entry.dataset["assessment"] = record.status === "answered" ? "balanced" : "failed"
        const heading =
          archived.kind === "chart"
            ? queryItemHeading(archived.record)
            : `${universeScopeLabel(archived.record.scope)} 유니버스 · ` +
              archived.record.created_at_utc.slice(0, 16).replace("T", " ")
        entry.append(
          createElement("span", "fj-history-instrument", heading),
          createElement("span", "fj-history-hypothesis", record.question.slice(0, 80)),
        )
        entry.addEventListener("click", (event) => {
          if (event.isTrusted && answer !== null) {
            if (archived.kind === "chart") {
              renderAnswer(answer, archived.record)
            } else {
              renderUniverseAnswer(answer, archived.record)
            }
          }
        })
        return entry
      }),
    )
  }

  const refreshList = async (): Promise<void> => {
    // 대시보드 공부방과 같은 전체 아카이브 — 차트를 가리지 않고 전 종목
    // 질의와 유니버스 질의를 병합해 최신순으로 보여준다.
    if (list === null) {
      return
    }
    try {
      const settings = await getSettings()
      const [chart, universe] = await Promise.all([
        listAllChartQueries(settings),
        listUniverseQueries(settings),
      ])
      if (!chart.ok) {
        list.replaceChildren(createElement("div", "fj-history-empty", chart.error))
        return
      }
      renderList(mergeQueryArchive(chart.items, universe.ok ? universe.items : []))
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

  const askUniverse = async (scope: UniverseScope, question: string): Promise<void> => {
    if (input === null || submit === null) {
      return
    }
    setStatus(`${universeScopeLabel(scope)} 스캔 산출물 분석 중… (최대 3분)`)
    const response = await askUniverseQuery(await getSettings(), scope, question)
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
      renderUniverseAnswer(answer, response.query)
    }
    await refreshList()
  }

  const askChart = async (question: string): Promise<void> => {
    if (input === null) {
      return
    }
    const { symbol, timeframe } = chartKeys(root)
    if (!symbol || !timeframe) {
      setStatus("질문과 종목·타임프레임이 필요합니다", "needed")
      return
    }
    setStatus("전체 이력 통계 계산 + 트레이더 분석 중… (최대 3분)")
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
  }

  const ask = async (): Promise<void> => {
    if (replayActive || input === null || submit === null) {
      return
    }
    const question = input.value.trim()
    if (!question) {
      setStatus("질문을 입력하세요", "needed")
      return
    }
    const scopeValue = scopeSelect?.value ?? "chart"
    submit.disabled = true
    try {
      if (isUniverseScope(scopeValue)) {
        await askUniverse(scopeValue, question)
      } else {
        await askChart(question)
      }
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
