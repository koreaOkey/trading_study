export const PAGE_METADATA_EVENT = "fractal-replay-journal:page-metadata"
export const PAGE_METADATA_REQUEST_EVENT = "fractal-replay-journal:request-page-metadata"

export type PageChartMetadata = {
  readonly symbol: string
  readonly timeframe: string
  readonly replayActive: boolean
  readonly replayTimestamp: number | null
  readonly requestId: string | null
}

export type PageMetadataRequest = {
  readonly requestId: string | null
}

export const PAGE_BARS_EVENT = "fractal-replay-journal:page-bars"
export const PAGE_BARS_REQUEST_EVENT = "fractal-replay-journal:request-page-bars"

export type PageBarsPayload = {
  readonly requestId: string
  readonly symbol: string
  readonly timeframe: string
  readonly columns: readonly string[]
  readonly rows: ReadonlyArray<ReadonlyArray<number | null>>
  readonly error: string | null
}

export type PageBarsRequest = {
  readonly requestId: string
}
