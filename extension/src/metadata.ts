import { getInputValue, getTextareaValue } from "./dom"
import type { CaptureDraftPayload, ConfirmedMetadata, Decision, WarningCode } from "./types"

export const extractSymbolCandidate = (): string => {
  const titleMatch = document.title.match(/\b[A-Z0-9]{4,8}\b/u)
  if (titleMatch?.[0] !== undefined) {
    return titleMatch[0]
  }
  const pathMatch = window.location.pathname.match(/\b[A-Z0-9]{4,8}\b/u)
  return pathMatch?.[0] ?? ""
}

export const extractTimeframeCandidate = (): string => {
  const titleMatch = document.title.match(/\b(1|3|5|15|30|60|120|240|1D|1W|1M)\b/u)
  return titleMatch?.[0] ?? "1D"
}

export const currentExchangeIso = (): string => {
  const local = new Date()
  const offset = 9 * 60 * 60 * 1000
  return new Date(local.getTime() + offset).toISOString().replace("Z", "+09:00")
}

export const today = (): string => new Date().toISOString().slice(0, 10)

export const buildConfirmedMetadata = (root: HTMLElement): ConfirmedMetadata => {
  const symbol = getInputValue(root, "symbol")
  return {
    symbol,
    provider: "kis",
    provider_symbol: getInputValue(root, "providerSymbol") || symbol,
    market_div_code: getInputValue(root, "marketDivCode") || "J",
    timeframe: getInputValue(root, "timeframe"),
    trade_date: getInputValue(root, "tradeDate"),
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

export const buildPayload = (root: HTMLElement, decision: Decision): CaptureDraftPayload => {
  const confirmed = buildConfirmedMetadata(root)
  return {
    extracted: {
      source_url: window.location.href,
      page_title: document.title || "TradingView",
      symbol_candidate: extractSymbolCandidate(),
      timeframe_candidate: extractTimeframeCandidate(),
      captured_at: new Date().toISOString(),
    },
    confirmed,
    decision,
    notes: getTextareaValue(root, "notes"),
    warnings: collectWarnings(confirmed),
  }
}
