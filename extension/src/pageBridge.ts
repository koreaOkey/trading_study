import {
  PAGE_BARS_EVENT,
  PAGE_BARS_REQUEST_EVENT,
  PAGE_METADATA_EVENT,
  PAGE_METADATA_REQUEST_EVENT,
} from "./bridgeProtocol"
import type { PageBarsPayload, PageChartMetadata } from "./bridgeProtocol"

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

type SeriesCapableChart = ExportCapableChart & {
  readonly getSeries?: () => { readonly data: () => SeriesDataApi }
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

const publishPageBars = async (requestId: string): Promise<void> => {
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
      rows,
      error: null,
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
    void publishPageBars(event.detail.requestId)
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
