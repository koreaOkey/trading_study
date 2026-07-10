import { getInputValue, getTextareaValue } from "./dom"
import type {
  CaptureDraftPayload,
  ConfirmedMetadata,
  Decision,
  ExtractedMetadata,
  WarningCode,
} from "./types"

export type CandidateMetadata = {
  readonly symbol: string
  readonly timeframe: string
  readonly decisionTime: string
  readonly replayActive: boolean
}

const symbolFromRaw = (raw: string): string => {
  const qualified = raw.match(/(?:^|\b)[A-Z][A-Z0-9_]*:([A-Z0-9][A-Z0-9.!-]{1,31})(?:\b|$)/u)
  if (qualified?.[1] !== undefined) {
    return qualified[1]
  }
  return raw.match(/\b[A-Z0-9]{4,12}\b/u)?.[0] ?? ""
}

export const extractSymbolCandidate = (): string => {
  const querySymbol = new URL(window.location.href).searchParams.get("symbol")
  if (querySymbol !== null) {
    const parsed = symbolFromRaw(querySymbol)
    if (parsed.length > 0) {
      return parsed
    }
  }
  const elements = document.querySelectorAll<HTMLElement>(
    'button[title="Symbol Search"], button[title="심볼 찾기"], button[aria-label="Change symbol"], button[aria-label="종목바꾸기"], canvas[aria-label]',
  )
  for (const element of Array.from(elements)) {
    const parsed = symbolFromRaw(
      `${element.textContent ?? ""} ${element.getAttribute("aria-label") ?? ""}`,
    )
    if (parsed.length > 0) {
      return parsed
    }
  }
  return symbolFromRaw(document.title)
}

export const normalizeTimeframeCandidate = (raw: string): string => {
  const compact = raw.trim().replace(/\s+/gu, " ")
  const upper = compact.toUpperCase()
  if (/^[1-9]\d*$/u.test(upper)) {
    return upper
  }
  const direct = upper.match(/^(\d+)(S|H|D|W|M)$/u)
  if (direct?.[1] !== undefined && direct[2] !== undefined) {
    const amount = Number(direct[1])
    switch (direct[2]) {
      case "S":
        return `${amount}S`
      case "H":
        return String(amount * 60)
      case "D":
        return `${amount}D`
      case "W":
        return `${amount}W`
      case "M":
        return `${amount}M`
    }
  }
  if (/^D$/u.test(upper)) return "1D"
  if (/^W$/u.test(upper)) return "1W"
  if (/^M$/u.test(upper)) return "1M"

  const localized = compact.match(
    /^(\d+)\s*(초|분|시간|날|일|주|달|개월|SECOND(?:S)?|MINUTE(?:S)?|HOUR(?:S)?|DAY(?:S)?|WEEK(?:S)?|MONTH(?:S)?)$/iu,
  )
  if (localized?.[1] === undefined || localized[2] === undefined) {
    return ""
  }
  const amount = Number(localized[1])
  const unit = localized[2].toUpperCase()
  if (unit === "초" || unit.startsWith("SECOND")) return `${amount}S`
  if (unit === "분" || unit.startsWith("MINUTE")) return String(amount)
  if (unit === "시간" || unit.startsWith("HOUR")) return String(amount * 60)
  if (unit === "날" || unit === "일" || unit.startsWith("DAY")) return `${amount}D`
  if (unit === "주" || unit.startsWith("WEEK")) return `${amount}W`
  return `${amount}M`
}

export const extractTimeframeCandidate = (): string => {
  const buttons = document.querySelectorAll<HTMLElement>("button[aria-label], button")
  for (const button of Array.from(buttons)) {
    const aria = button.getAttribute("aria-label") ?? ""
    const parsed = normalizeTimeframeCandidate(aria)
    if (parsed.length > 0) {
      return parsed
    }
  }
  const titleMatch = document.title.match(/\b(\d+(?:S|H|D|W|M))\b/iu)
  return titleMatch?.[1] === undefined ? "" : normalizeTimeframeCandidate(titleMatch[1])
}

const datePartsInTimezone = (date: Date, timeZone: string): Readonly<Record<string, string>> =>
  Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(date)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  )

export const formatReplayDecisionTime = (epoch: number, timeZone: string): string => {
  const date = new Date(epoch < 1_000_000_000_000 ? epoch * 1_000 : epoch)
  const parts = datePartsInTimezone(date, timeZone)
  const year = parts["year"] ?? "0000"
  const month = parts["month"] ?? "00"
  const day = parts["day"] ?? "00"
  const hour = parts["hour"] ?? "00"
  const minute = parts["minute"] ?? "00"
  const second = parts["second"] ?? "00"
  const localAsUtc = Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), Number(second))
  const offsetMinutes = Math.round((localAsUtc - date.getTime()) / 60_000)
  const sign = offsetMinutes >= 0 ? "+" : "-"
  const absoluteOffset = Math.abs(offsetMinutes)
  const offsetHours = String(Math.floor(absoluteOffset / 60)).padStart(2, "0")
  const offsetRemainder = String(absoluteOffset % 60).padStart(2, "0")
  return `${year}-${month}-${day}T${hour}:${minute}:${second}${sign}${offsetHours}:${offsetRemainder}`
}

export const currentExchangeIso = (): string => formatReplayDecisionTime(Date.now(), "Asia/Seoul")

export const fallbackCandidateMetadata = (): CandidateMetadata => ({
  symbol: extractSymbolCandidate(),
  timeframe: extractTimeframeCandidate(),
  decisionTime: currentExchangeIso(),
  replayActive: false,
})

export const buildConfirmedMetadata = (root: HTMLElement): ConfirmedMetadata => {
  const symbol = getInputValue(root, "symbol")
  return {
    symbol,
    provider: "kis",
    provider_symbol: getInputValue(root, "providerSymbol") || symbol,
    market_div_code: getInputValue(root, "marketDivCode") || "J",
    timeframe: getInputValue(root, "timeframe"),
    decision_time_exchange: getInputValue(root, "decisionTime") || currentExchangeIso(),
    exchange_tz: getInputValue(root, "exchangeTz") || "Asia/Seoul",
    price_basis: getInputValue(root, "priceBasis") || "unknown_unadjusted_assumed",
    session_state: getInputValue(root, "sessionState") || "regular",
    provider_status: "candidate",
    scenario: "wait",
    confidence: 3,
    invalidation: getInputValue(root, "invalidation"),
  }
}

export const collectWarnings = (metadata: ConfirmedMetadata): readonly WarningCode[] => {
  const warnings: WarningCode[] = []
  if (
    metadata.symbol.length === 0 ||
    metadata.provider_symbol.length === 0 ||
    metadata.provider_status !== "ready" ||
    metadata.provider_symbol !== metadata.symbol
  ) {
    warnings.push("provider_symbol_unconfirmed")
  }
  if (metadata.price_basis === "unknown_unadjusted_assumed") {
    warnings.push("price_basis_unverified")
  }
  return warnings
}

const buildExtractedMetadata = (candidate: CandidateMetadata): ExtractedMetadata => ({
  source_url: window.location.href,
  page_title: document.title || "TradingView",
  symbol_candidate: candidate.symbol,
  timeframe_candidate: candidate.timeframe,
  decision_time_candidate: candidate.decisionTime,
  replay_active: candidate.replayActive,
  captured_at: new Date().toISOString(),
})

export const buildPayload = (
  root: HTMLElement,
  decision: Decision,
  candidate: CandidateMetadata = fallbackCandidateMetadata(),
): CaptureDraftPayload => {
  const confirmed = buildConfirmedMetadata(root)
  return {
    extracted: buildExtractedMetadata(candidate),
    confirmed,
    decision,
    notes: getTextareaValue(root, "notes"),
    warnings: collectWarnings(confirmed),
  }
}
