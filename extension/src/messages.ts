import {
  askChartQueryMessageResponseSchema,
  askUniverseQueryMessageResponseSchema,
  barCoverageMessageResponseSchema,
  healthMessageResponseSchema,
  listChartQueriesMessageResponseSchema,
  listUniverseQueriesMessageResponseSchema,
  recentReviewsMessageResponseSchema,
  registerBarSeriesMessageResponseSchema,
  reviewCaptureMessageResponseSchema,
  saveCaptureMessageResponseSchema,
} from "./messageProtocol"
import type {
  AskChartQueryMessageResponse,
  AskUniverseQueryMessageResponse,
  BarCoverageMessageResponse,
  HealthMessageResponse,
  ListChartQueriesMessageResponse,
  ListUniverseQueriesMessageResponse,
  RecentReviewsMessageResponse,
  RegisterBarSeriesMessageResponse,
  ReviewCaptureMessageResponse,
  SaveCaptureMessageResponse,
  UniverseScope,
} from "./messageProtocol"
import type {
  CaptureDraftPayload,
  CapturePayload,
  ExtensionSettings,
} from "./types"

export const checkBackendHealth = async (
  settings: ExtensionSettings,
): Promise<HealthMessageResponse> => {
  return healthMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({ kind: "check-health", settings }),
  )
}

export const saveCapture = async (
  settings: ExtensionSettings,
  payload: CaptureDraftPayload,
  captureRequestId: string,
): Promise<SaveCaptureMessageResponse> => {
  return saveCaptureMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({ kind: "save-capture", settings, payload, captureRequestId }),
  )
}

export const retryCapture = async (
  settings: ExtensionSettings,
  payload: CapturePayload,
): Promise<SaveCaptureMessageResponse> => {
  return saveCaptureMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({ kind: "retry-capture", settings, payload }),
  )
}

export const reviewCapture = async (
  settings: ExtensionSettings,
  captureId: string,
): Promise<ReviewCaptureMessageResponse> => {
  return reviewCaptureMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({ kind: "review-capture", settings, captureId }),
  )
}

export const registerBarSeries = async (
  settings: ExtensionSettings,
  symbol: string,
  timeframe: string,
  csvText: string,
): Promise<RegisterBarSeriesMessageResponse> => {
  return registerBarSeriesMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({
      kind: "register-bar-series",
      settings,
      symbol,
      timeframe,
      csvText,
    }),
  )
}

export const getBarCoverage = async (
  settings: ExtensionSettings,
  symbol: string,
  timeframe: string,
): Promise<BarCoverageMessageResponse> => {
  return barCoverageMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({
      kind: "get-bar-coverage",
      settings,
      symbol,
      timeframe,
    }),
  )
}

export const getRecentReviews = async (
  settings: ExtensionSettings,
  symbol: string,
  limit = 20,
): Promise<RecentReviewsMessageResponse> => {
  return recentReviewsMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({
      kind: "get-recent-reviews",
      settings,
      symbol,
      limit,
    }),
  )
}

export const askChartQuery = async (
  settings: ExtensionSettings,
  symbol: string,
  timeframe: string,
  question: string,
): Promise<AskChartQueryMessageResponse> => {
  return askChartQueryMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({
      kind: "ask-chart-query",
      settings,
      symbol,
      timeframe,
      question,
    }),
  )
}

export const listChartQueries = async (
  settings: ExtensionSettings,
  symbol: string,
  timeframe: string,
  limit = 20,
): Promise<ListChartQueriesMessageResponse> => {
  return listChartQueriesMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({
      kind: "list-chart-queries",
      settings,
      symbol,
      timeframe,
      limit,
    }),
  )
}

export const askUniverseQuery = async (
  settings: ExtensionSettings,
  scope: UniverseScope,
  question: string,
): Promise<AskUniverseQueryMessageResponse> => {
  return askUniverseQueryMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({
      kind: "ask-universe-query",
      settings,
      scope,
      question,
    }),
  )
}

export const listAllChartQueries = async (
  settings: ExtensionSettings,
  limit = 200,
): Promise<ListChartQueriesMessageResponse> => {
  return listChartQueriesMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({
      kind: "list-chart-queries",
      settings,
      limit,
    }),
  )
}

export const listUniverseQueries = async (
  settings: ExtensionSettings,
  limit = 200,
): Promise<ListUniverseQueriesMessageResponse> => {
  return listUniverseQueriesMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({
      kind: "list-universe-queries",
      settings,
      limit,
    }),
  )
}
