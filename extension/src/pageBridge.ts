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
    const chart = api.activeChart() as ExportCapableChart
    if (typeof chart.exportData !== "function") {
      throw new Error("export_data_unavailable")
    }
    const result = await chart.exportData({
      includeTime: true,
      includeSeries: true,
      includedStudies: "all",
    })
    detail = {
      requestId,
      symbol: chart.symbol(),
      timeframe: chart.resolution(),
      columns: result.schema.map(columnTitle),
      rows: result.data,
      error: null,
    }
  } catch (error) {
    detail = { ...base, error: error instanceof Error ? error.message : "export_failed" }
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
