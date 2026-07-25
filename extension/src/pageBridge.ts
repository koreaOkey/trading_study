import {
  PAGE_BARS_EVENT,
  PAGE_BARS_PROGRESS_EVENT,
  PAGE_BARS_REQUEST_EVENT,
  PAGE_METADATA_EVENT,
  PAGE_METADATA_REQUEST_EVENT,
} from "./bridgeProtocol"
import type { PageBarsPayload, PageBarsProgress, PageChartMetadata } from "./bridgeProtocol"

type WatchedValue<T> = {
  readonly value: () => T
}

type MaybeWatched<T> = T | WatchedValue<T>

type TradingViewChartApi = {
  readonly symbol: () => string
  readonly resolution: () => string
}

type TradingViewReplayApi = {
  readonly isReplayStarted: () => MaybeWatched<boolean>
  readonly currentDate: () => MaybeWatched<number | null>
}

type TradingViewApi = {
  readonly activeChart: () => TradingViewChartApi
  readonly replayApi: () => Promise<TradingViewReplayApi>
}

type TradingViewWindow = Window & {
  readonly TradingViewApi?: TradingViewApi
}

const isWatchedValue = <T>(value: MaybeWatched<T>): value is WatchedValue<T> =>
  typeof value === "object" && value !== null && "value" in value

const unwrap = <T>(value: MaybeWatched<T>): T =>
  isWatchedValue(value) ? value.value() : value

const publishPageMetadata = async (requestId: string | null): Promise<void> => {
  const api = (window as TradingViewWindow).TradingViewApi
  if (api === undefined) {
    return
  }
  const chart = api.activeChart()
  const replay = await api.replayApi()
  const detail: PageChartMetadata = {
    symbol: chart.symbol(),
    timeframe: chart.resolution(),
    replayActive: unwrap(replay.isReplayStarted()),
    replayTimestamp: unwrap(replay.currentDate()),
    requestId,
  }
  document.dispatchEvent(new CustomEvent<PageChartMetadata>(PAGE_METADATA_EVENT, { detail }))
}

const publishSafely = async (requestId: string | null): Promise<void> => {
  try {
    await publishPageMetadata(requestId)
  } catch (error) {
    if (error instanceof Error) {
      console.warn("[Fractal Replay Journal] TradingView metadata unavailable", error)
      return
    }
    throw error
  }
}

const requestPublish = (event: Event): void => {
  const requestId =
    event instanceof CustomEvent &&
    typeof event.detail === "object" &&
    event.detail !== null &&
    "requestId" in event.detail &&
    typeof event.detail.requestId === "string"
      ? event.detail.requestId
      : null
  void publishSafely(requestId)
}

type ExportDataField = {
  readonly type?: string
  readonly plotTitle?: string
  readonly sourceTitle?: string
}

type ExportDataResult = {
  readonly schema: readonly ExportDataField[]
  readonly data: ReadonlyArray<ReadonlyArray<number | null>>
}

type ExportCapableChart = TradingViewChartApi & {
  readonly exportData?: (options?: {
    readonly includeTime?: boolean
    readonly includeSeries?: boolean
    readonly includedStudies?: readonly string[] | "all"
  }) => Promise<ExportDataResult>
}

const columnTitle = (field: ExportDataField, index: number): string => {
  if (field.type === "time") {
    return "time"
  }
  return field.plotTitle || field.sourceTitle || `col${index}`
}

type SeriesBarsApi = {
  readonly size: () => number
  readonly firstIndex?: () => number
  readonly valueAt: (index: number) => unknown
}

type SeriesDataApi = {
  readonly bars: () => SeriesBarsApi
}

type SeriesApi = {
  readonly data: () => SeriesDataApi
  readonly endOfData?: () => boolean
  readonly isLoading?: () => boolean
}

type SeriesCapableChart = ExportCapableChart & {
  readonly getSeries?: () => SeriesApi
  readonly canZoomOut?: () => boolean
  readonly executeActionById?: (actionId: string) => void
}

const SERIES_COLUMNS = ["time", "open", "high", "low", "close", "volume"] as const

// The chart's in-memory series rows are [time, open, high, low, close, volume].
// Unlike exportData this path has no plan gate, so it serves as the fallback
// when TradingView rejects the export (e.g. "Data export is not supported").
const readSeriesRows = (
  chart: SeriesCapableChart,
): ReadonlyArray<ReadonlyArray<number | null>> => {
  if (typeof chart.getSeries !== "function") {
    throw new Error("series_unavailable")
  }
  const bars = chart.getSeries().data().bars()
  const first = typeof bars.firstIndex === "function" ? bars.firstIndex() : 0
  const rows: Array<ReadonlyArray<number | null>> = []
  const size = bars.size()
  for (let index = first; index < first + size; index += 1) {
    const value = bars.valueAt(index)
    if (!Array.isArray(value)) {
      continue
    }
    rows.push(
      value
        .slice(0, SERIES_COLUMNS.length)
        .map((cell) => (typeof cell === "number" && Number.isFinite(cell) ? cell : null)),
    )
  }
  if (rows.length === 0) {
    throw new Error("series_empty")
  }
  return rows
}

const describeThrown = (error: unknown): string =>
  error instanceof Error ? error.message : String(error)

// The bars payload schema on the content-script side rejects more than 50k
// rows, so the loader stops early and the reader keeps the newest rows.
const MAX_FULL_HISTORY_BARS = 45_000
const MAX_PAYLOAD_ROWS = 50_000
const MAX_LOAD_ROUNDS = 150
const MAX_STALL_ROUNDS = 5

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => window.setTimeout(resolve, ms))

const barCount = (chart: SeriesCapableChart): number => {
  try {
    if (typeof chart.getSeries !== "function") {
      return 0
    }
    return chart.getSeries().data().bars().size()
  } catch {
    return 0
  }
}

// TradingView keeps only the bars a user has scrolled into view in memory and
// gates the range-loading APIs (setVisibleRange throws "Not implemented"), so
// the only ungated way to reach full history is to replay the user gestures:
// ctrl+wheel zoom-out until the zoom limit, then wheel-pan into the past.
// getSeries().endOfData() reports when the exchange history is exhausted.
const loadFullHistory = async (
  chart: SeriesCapableChart,
  requestId: string,
): Promise<void> => {
  const series = typeof chart.getSeries === "function" ? chart.getSeries() : null
  if (series === null || typeof series.endOfData !== "function") {
    return
  }
  const canvas =
    document.querySelector<HTMLCanvasElement>(".chart-markup-table canvas") ??
    document.querySelector("canvas")
  if (canvas === null || barCount(chart) === 0) {
    return
  }
  const endOfData = (): boolean => {
    try {
      return series.endOfData?.() === true
    } catch {
      return false
    }
  }
  const isLoading = (): boolean => {
    try {
      return series.isLoading?.() === true
    } catch {
      return false
    }
  }
  const rect = canvas.getBoundingClientRect()
  const wheel = (init: WheelEventInit): void => {
    canvas.dispatchEvent(
      new WheelEvent("wheel", {
        bubbles: true,
        cancelable: true,
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + rect.height / 2,
        ...init,
      }),
    )
  }
  let stall = 0
  for (let round = 0; round < MAX_LOAD_ROUNDS && stall < MAX_STALL_ROUNDS; round += 1) {
    if (endOfData() || barCount(chart) >= MAX_FULL_HISTORY_BARS) {
      break
    }
    const before = barCount(chart)
    if (chart.canZoomOut?.() === true) {
      for (let i = 0; i < 4; i += 1) {
        wheel({ deltaY: 120, ctrlKey: true })
      }
    } else {
      for (let i = 0; i < 12; i += 1) {
        wheel({ deltaX: -300 })
      }
    }
    for (let wait = 0; wait < 40 && isLoading(); wait += 1) {
      await sleep(250)
    }
    await sleep(300)
    stall = barCount(chart) === before ? stall + 1 : 0
    const progress: PageBarsProgress = { requestId, loadedBars: barCount(chart) }
    document.dispatchEvent(
      new CustomEvent<PageBarsProgress>(PAGE_BARS_PROGRESS_EVENT, { detail: progress }),
    )
  }
}

// The load loop leaves the viewport zoomed out deep in the past; jump back to
// the latest bar so the chart looks untouched. Cosmetic only — never throw.
const restoreDefaultView = (chart: SeriesCapableChart): void => {
  try {
    chart.executeActionById?.("timeScaleReset")
  } catch {
    // ignored
  }
}

const publishPageBars = async (requestId: string, fullHistory: boolean): Promise<void> => {
  const base: Omit<PageBarsPayload, "error"> = {
    requestId,
    symbol: "",
    timeframe: "",
    columns: [],
    rows: [],
  }
  let detail: PageBarsPayload
  try {
    const api = (window as TradingViewWindow).TradingViewApi
    if (api === undefined) {
      throw new Error("tradingview_api_unavailable")
    }
    const chart = api.activeChart() as SeriesCapableChart
    if (fullHistory) {
      try {
        await loadFullHistory(chart, requestId)
      } catch (error) {
        // A partial history is still a valid extract; registration merges, so
        // the next click resumes from wherever this attempt stopped.
        console.warn("[Fractal Replay Journal] full-history load stopped", error)
      }
    }
    let columns: readonly string[] | null = null
    let rows: ReadonlyArray<ReadonlyArray<number | null>> | null = null
    let exportError: string | null = null
    if (typeof chart.exportData === "function") {
      try {
        const result = await chart.exportData({
          includeTime: true,
          includeSeries: true,
          includedStudies: "all",
        })
        columns = result.schema.map(columnTitle)
        rows = result.data
      } catch (error) {
        exportError = describeThrown(error)
      }
    }
    if (rows === null || columns === null) {
      try {
        rows = readSeriesRows(chart)
        columns = SERIES_COLUMNS
      } catch (error) {
        throw new Error(
          exportError === null
            ? describeThrown(error)
            : `${exportError} / ${describeThrown(error)}`,
        )
      }
    }
    detail = {
      requestId,
      symbol: chart.symbol(),
      timeframe: chart.resolution(),
      columns: [...columns],
      rows: rows.length > MAX_PAYLOAD_ROWS ? rows.slice(-MAX_PAYLOAD_ROWS) : rows,
      error: null,
    }
    if (fullHistory) {
      restoreDefaultView(chart)
    }
  } catch (error) {
    detail = { ...base, error: describeThrown(error) }
  }
  document.dispatchEvent(new CustomEvent<PageBarsPayload>(PAGE_BARS_EVENT, { detail }))
}

const requestBars = (event: Event): void => {
  if (
    event instanceof CustomEvent &&
    typeof event.detail === "object" &&
    event.detail !== null &&
    "requestId" in event.detail &&
    typeof event.detail.requestId === "string"
  ) {
    const fullHistory =
      "fullHistory" in event.detail && event.detail.fullHistory === true
    void publishPageBars(event.detail.requestId, fullHistory)
  }
}

document.addEventListener(PAGE_METADATA_REQUEST_EVENT, requestPublish)
document.addEventListener(PAGE_BARS_REQUEST_EVENT, requestBars)
let pollInFlight = false
const poll = (): void => {
  if (pollInFlight) {
    return
  }
  pollInFlight = true
  void publishSafely(null).finally(() => {
    pollInFlight = false
  })
}
window.setInterval(poll, 750)
poll()
