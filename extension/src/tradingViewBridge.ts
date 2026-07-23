import { z } from "zod"

import {
  PAGE_BARS_EVENT,
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

export const requestPageBars = (timeoutMs = 15_000): Promise<PageBars | null> =>
  new Promise((resolve) => {
    const finish = (bars: PageBars | null): void => {
      window.clearTimeout(timeoutId)
      document.removeEventListener(PAGE_BARS_EVENT, handleBars)
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
    const requestId = crypto.randomUUID()
    const timeoutId = window.setTimeout(() => finish(null), timeoutMs)
    document.addEventListener(PAGE_BARS_EVENT, handleBars)
    document.dispatchEvent(
      new CustomEvent(PAGE_BARS_REQUEST_EVENT, { detail: { requestId } }),
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
