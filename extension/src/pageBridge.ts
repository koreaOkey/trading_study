import {
  PAGE_METADATA_EVENT,
  PAGE_METADATA_REQUEST_EVENT,
} from "./bridgeProtocol"
import type { PageChartMetadata } from "./bridgeProtocol"

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

document.addEventListener(PAGE_METADATA_REQUEST_EVENT, requestPublish)
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
