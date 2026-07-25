import { z } from "zod"

import {
  captureDraftPayloadSchema,
  capturePayloadSchema,
  decisionReviewResultSchema,
  warningValues,
} from "./types"
import type {
  CaptureDraftPayload,
  CapturePayload,
  DecisionReviewResult,
  ExtensionSettings,
  WarningCode,
} from "./types"

export type CheckHealthMessage = {
  readonly kind: "check-health"
  readonly settings: ExtensionSettings
}

export type SaveCaptureMessage = {
  readonly kind: "save-capture"
  readonly settings: ExtensionSettings
  readonly payload: CaptureDraftPayload
  readonly captureRequestId: string
}

export type RetryCaptureMessage = {
  readonly kind: "retry-capture"
  readonly settings: ExtensionSettings
  readonly payload: CapturePayload
}

export type ReviewCaptureMessage = {
  readonly kind: "review-capture"
  readonly settings: ExtensionSettings
  readonly captureId: string
}

export type RegisterBarSeriesMessage = {
  readonly kind: "register-bar-series"
  readonly settings: ExtensionSettings
  readonly symbol: string
  readonly timeframe: string
  readonly csvText: string
}

export type BarCoverageMessage = {
  readonly kind: "get-bar-coverage"
  readonly settings: ExtensionSettings
  readonly symbol: string
  readonly timeframe: string
}

export type RecentReviewsMessage = {
  readonly kind: "get-recent-reviews"
  readonly settings: ExtensionSettings
  readonly symbol: string
  readonly limit: number
}

export type AskChartQueryMessage = {
  readonly kind: "ask-chart-query"
  readonly settings: ExtensionSettings
  readonly symbol: string
  readonly timeframe: string
  readonly question: string
}

export type ListChartQueriesMessage = {
  readonly kind: "list-chart-queries"
  readonly settings: ExtensionSettings
  readonly symbol: string
  readonly timeframe: string
  readonly limit: number
}

export type CaptureMessage =
  | CheckHealthMessage
  | SaveCaptureMessage
  | RetryCaptureMessage
  | ReviewCaptureMessage
  | RegisterBarSeriesMessage
  | BarCoverageMessage
  | RecentReviewsMessage
  | AskChartQueryMessage
  | ListChartQueriesMessage

export type HealthMessageResponse =
  | { readonly ok: true; readonly status: number }
  | { readonly ok: false; readonly error: string }

export type SaveCaptureMessageResponse =
  | { readonly ok: true; readonly id: string; readonly warnings: readonly WarningCode[] }
  | { readonly ok: false; readonly error: string; readonly retry_payload?: CapturePayload | undefined }

export type ReviewCaptureMessageResponse =
  | { readonly ok: true; readonly result: DecisionReviewResult }
  | { readonly ok: false; readonly error: string }

export const healthMessageResponseSchema = z.discriminatedUnion("ok", [
  z.object({ ok: z.literal(true), status: z.number() }),
  z.object({ ok: z.literal(false), error: z.string() }),
])

export const saveCaptureMessageResponseSchema = z.discriminatedUnion("ok", [
  z.object({ ok: z.literal(true), id: z.string(), warnings: z.array(z.enum(warningValues)) }),
  z.object({ ok: z.literal(false), error: z.string(), retry_payload: capturePayloadSchema.optional() }),
])

export const reviewCaptureMessageResponseSchema = z.discriminatedUnion("ok", [
  z.object({ ok: z.literal(true), result: decisionReviewResultSchema }),
  z.object({ ok: z.literal(false), error: z.string() }),
])

export const barSeriesCoverageSchema = z.object({
  symbol: z.string(),
  timeframe: z.string(),
  bar_count: z.number().int().nonnegative(),
  first_time_exchange: z.string(),
  last_time_exchange: z.string(),
})

export type BarSeriesCoverage = z.infer<typeof barSeriesCoverageSchema>

export const registerBarSeriesMessageResponseSchema = z.discriminatedUnion("ok", [
  z.object({
    ok: z.literal(true),
    coverage: barSeriesCoverageSchema,
    reviews: z.array(decisionReviewResultSchema),
  }),
  z.object({ ok: z.literal(false), error: z.string() }),
])

export type RegisterBarSeriesMessageResponse = z.infer<
  typeof registerBarSeriesMessageResponseSchema
>

export const barCoverageMessageResponseSchema = z.discriminatedUnion("ok", [
  z.object({
    ok: z.literal(true),
    registered: z.boolean(),
    coverage: barSeriesCoverageSchema.nullable(),
  }),
  z.object({ ok: z.literal(false), error: z.string() }),
])

export type BarCoverageMessageResponse = z.infer<typeof barCoverageMessageResponseSchema>

export const reviewHistoryItemSchema = z.object({
  capture_id: z.string(),
  created_at: z.string(),
  symbol: z.string(),
  symbol_name: z.string().optional().default(""),
  timeframe: z.string(),
  decision_time_exchange: z.string(),
  hypothesis: z.string(),
  decision_note: z.string(),
  review: decisionReviewResultSchema.nullable(),
})

export type ReviewHistoryItem = z.infer<typeof reviewHistoryItemSchema>

export const recentReviewsMessageResponseSchema = z.discriminatedUnion("ok", [
  z.object({ ok: z.literal(true), items: z.array(reviewHistoryItemSchema) }),
  z.object({ ok: z.literal(false), error: z.string() }),
])

export type RecentReviewsMessageResponse = z.infer<typeof recentReviewsMessageResponseSchema>

export const chartQueryRecordSchema = z.object({
  query_id: z.string(),
  created_at_utc: z.string(),
  symbol: z.string(),
  timeframe: z.string(),
  question: z.string(),
  status: z.enum(["answered", "failed"]),
  answer: z.string().optional().default(""),
  error_code: z.string().optional().default(""),
  model: z.string().optional().default(""),
  bar_count: z.number().int().nonnegative().optional().default(0),
  first_bar_exchange: z.string().optional().default(""),
  last_bar_exchange: z.string().optional().default(""),
})

export type ChartQueryRecord = z.infer<typeof chartQueryRecordSchema>

export const askChartQueryMessageResponseSchema = z.discriminatedUnion("ok", [
  z.object({ ok: z.literal(true), query: chartQueryRecordSchema }),
  z.object({ ok: z.literal(false), error: z.string() }),
])

export type AskChartQueryMessageResponse = z.infer<typeof askChartQueryMessageResponseSchema>

export const listChartQueriesMessageResponseSchema = z.discriminatedUnion("ok", [
  z.object({ ok: z.literal(true), items: z.array(chartQueryRecordSchema) }),
  z.object({ ok: z.literal(false), error: z.string() }),
])

export type ListChartQueriesMessageResponse = z.infer<
  typeof listChartQueriesMessageResponseSchema
>

const settingsSchema = z.object({ apiBaseUrl: z.string(), apiToken: z.string() })

export const extensionMessageSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("check-health"), settings: settingsSchema }),
  z.object({
    kind: z.literal("save-capture"),
    settings: settingsSchema,
    payload: captureDraftPayloadSchema,
    captureRequestId: z.string().uuid(),
  }),
  z.object({
    kind: z.literal("retry-capture"),
    settings: settingsSchema,
    payload: capturePayloadSchema,
  }),
  z.object({
    kind: z.literal("review-capture"),
    settings: settingsSchema,
    captureId: z.string().min(1).max(128),
  }),
  z.object({
    kind: z.literal("register-bar-series"),
    settings: settingsSchema,
    symbol: z.string().min(1).max(32),
    timeframe: z.string().min(1).max(16),
    csvText: z.string().min(1).max(8_000_000),
  }),
  z.object({
    kind: z.literal("get-bar-coverage"),
    settings: settingsSchema,
    symbol: z.string().min(1).max(32),
    timeframe: z.string().min(1).max(16),
  }),
  z.object({
    kind: z.literal("get-recent-reviews"),
    settings: settingsSchema,
    symbol: z.string().min(1).max(32),
    limit: z.number().int().min(1).max(50),
  }),
  z.object({
    kind: z.literal("ask-chart-query"),
    settings: settingsSchema,
    symbol: z.string().min(1).max(32),
    timeframe: z.string().min(1).max(16),
    question: z.string().min(1).max(2_000),
  }),
  z.object({
    kind: z.literal("list-chart-queries"),
    settings: settingsSchema,
    symbol: z.string().min(1).max(32),
    timeframe: z.string().min(1).max(16),
    limit: z.number().int().min(1).max(50),
  }),
])
