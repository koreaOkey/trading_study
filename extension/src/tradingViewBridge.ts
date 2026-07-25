import { z } from "zod"

import {
  PAGE_BARS_EVENT,
  PAGE_BARS_PROGRESS_EVENT,
  PAGE_BARS_REQUEST_EVENT,
  PAGE_METADATA_EVENT,
  PAGE_METADATA_REQUEST_EVENT,
} from "./bridgeProtocol"
import type { PageChartMetadata } from "./bridgeProtocol"
import {
  currentExchangeIso,
  formatReplayDecisionTime,
  normalizeTimeframeCandidate,
} from "./metadata"
import type { CandidateMetadata } from "./metadata"

const pageChartMetadataSchema = z.object({
  symbol: z.string().max(32),
  timeframe: z.string().max(16),
  replayActive: z.boolean(),
  replayTimestamp: z.number().finite().min(0).max(4_102_444_800_000).nullable(),
  requestId: z.string().max(64).nullable().optional().default(null),
})

const normalizeSymbol = (raw: string): string =>
  raw.match(/:([A-Z0-9][A-Z0-9.!-]{1,31})$/u)?.[1] ??
  raw.match(/^[A-Z0-9][A-Z0-9.!-]{1,31}$/u)?.[0] ??
  ""

export const candidateFromPageMetadata = (page: PageChartMetadata): CandidateMetadata => ({
  symbol: normalizeSymbol(page.symbol),
  timeframe: normalizeTimeframeCandidate(page.timeframe),
  decisionTime:
    page.replayActive && page.replayTimestamp !== null
      ? formatReplayDecisionTime(page.replayTimestamp, "Asia/Seoul")
      : currentExchangeIso(),
  replayActive: page.replayActive,
})

export const requestPageMetadata = (): void => {
  document.dispatchEvent(
    new CustomEvent(PAGE_METADATA_REQUEST_EVENT, { detail: { requestId: null } }),
  )
}

type ParsedPageMetadata = {
  readonly candidate: CandidateMetadata
  readonly requestId: string | null
}

const metadataFromEvent = (event: Event): ParsedPageMetadata | null => {
  if (!(event instanceof CustomEvent)) {
    return null
  }
  const parsed = pageChartMetadataSchema.safeParse(event.detail)
  return parsed.success
    ? { candidate: candidateFromPageMetadata(parsed.data), requestId: parsed.data.requestId }
    : null
}

export const requestFreshPageMetadata = (timeoutMs = 1_200): Promise<CandidateMetadata | null> =>
  new Promise((resolve) => {
    const finish = (candidate: CandidateMetadata | null): void => {
      window.clearTimeout(timeoutId)
      document.removeEventListener(PAGE_METADATA_EVENT, handleMetadata)
      resolve(candidate)
    }
    const handleMetadata = (event: Event): void => {
      const metadata = metadataFromEvent(event)
      if (metadata?.requestId === requestId) {
        finish(metadata.candidate)
      }
    }
    const requestId = crypto.randomUUID()
    const timeoutId = window.setTimeout(() => finish(null), timeoutMs)
    document.addEventListener(PAGE_METADATA_EVENT, handleMetadata)
    document.dispatchEvent(
      new CustomEvent(PAGE_METADATA_REQUEST_EVENT, { detail: { requestId } }),
    )
  })

const pageBarsSchema = z.object({
  requestId: z.string().max(64),
  symbol: z.string().max(64),
  timeframe: z.string().max(16),
  columns: z.array(z.string().max(64)).max(64),
  rows: z.array(z.array(z.number().finite().nullable()).max(64)).max(50_000),
  error: z.string().max(400).nullable(),
})

export type PageBars = z.infer<typeof pageBarsSchema>

const pageBarsProgressSchema = z.object({
  requestId: z.string().max(64),
  loadedBars: z.number().finite().min(0),
})

export type PageBarsOptions = {
  readonly fullHistory?: boolean
  readonly onProgress?: (loadedBars: number) => void
  readonly timeoutMs?: number
}

export const requestPageBars = (options: PageBarsOptions = {}): Promise<PageBars | null> =>
  new Promise((resolve) => {
    // The full-history load walks the chart into the past round by round, so
    // the deadline is idle-based: every progress event proves the page bridge
    // is still working and re-arms the timer. An old bridge build that ignores
    // the flag simply answers fast with whatever bars are loaded.
    const timeoutMs = options.timeoutMs ?? (options.fullHistory === true ? 60_000 : 15_000)
    const finish = (bars: PageBars | null): void => {
      window.clearTimeout(timeoutId)
      document.removeEventListener(PAGE_BARS_EVENT, handleBars)
      document.removeEventListener(PAGE_BARS_PROGRESS_EVENT, handleProgress)
      resolve(bars)
    }
    const handleBars = (event: Event): void => {
      if (!(event instanceof CustomEvent)) {
        return
      }
      const parsed = pageBarsSchema.safeParse(event.detail)
      if (parsed.success && parsed.data.requestId === requestId) {
        finish(parsed.data)
      }
    }
    const handleProgress = (event: Event): void => {
      if (!(event instanceof CustomEvent)) {
        return
      }
      const parsed = pageBarsProgressSchema.safeParse(event.detail)
      if (parsed.success && parsed.data.requestId === requestId) {
        window.clearTimeout(timeoutId)
        timeoutId = window.setTimeout(() => finish(null), timeoutMs)
        options.onProgress?.(parsed.data.loadedBars)
      }
    }
    const requestId = crypto.randomUUID()
    let timeoutId = window.setTimeout(() => finish(null), timeoutMs)
    document.addEventListener(PAGE_BARS_EVENT, handleBars)
    document.addEventListener(PAGE_BARS_PROGRESS_EVENT, handleProgress)
    document.dispatchEvent(
      new CustomEvent(PAGE_BARS_REQUEST_EVENT, {
        detail: { requestId, fullHistory: options.fullHistory === true },
      }),
    )
  })

export const bindTradingViewBridge = (
  onMetadata: (metadata: CandidateMetadata) => void,
): (() => void) => {
  const handleMetadata = (event: Event): void => {
    const metadata = metadataFromEvent(event)
    if (metadata !== null) {
      onMetadata(metadata.candidate)
    }
  }
  document.addEventListener(PAGE_METADATA_EVENT, handleMetadata)
  requestPageMetadata()
  return () => document.removeEventListener(PAGE_METADATA_EVENT, handleMetadata)
}
