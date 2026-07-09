import { z } from "zod"

export const decisionValues = ["long", "short", "skip", "watch"] as const
export type Decision = (typeof decisionValues)[number]

export const warningValues = [
  "provider_symbol_unconfirmed",
  "price_basis_unverified",
  "partial_data",
  "empty_data",
  "request_date_mismatch",
  "after_regular_close_clamped",
  "close_auction_bar",
  "backend_unavailable",
  "retry_exhausted",
] as const
export type WarningCode = (typeof warningValues)[number]

export const providerStatusValues = ["candidate", "ready", "partial", "mismatch", "empty"] as const
export type ProviderStatus = (typeof providerStatusValues)[number]

export type ExtractedMetadata = {
  readonly source_url: string
  readonly page_title: string
  readonly symbol_candidate: string
  readonly timeframe_candidate: string
  readonly captured_at: string
}

export const extractedMetadataSchema = z.object({
  source_url: z.string(),
  page_title: z.string(),
  symbol_candidate: z.string(),
  timeframe_candidate: z.string(),
  captured_at: z.string(),
})

export type ConfirmedMetadata = {
  readonly symbol: string
  readonly provider: string
  readonly provider_symbol: string
  readonly market_div_code: string
  readonly timeframe: string
  readonly trade_date: string
  readonly decision_time_exchange: string
  readonly exchange_tz: string
  readonly price_basis: string
  readonly session_state: string
  readonly provider_status: ProviderStatus
  readonly scenario: string
  readonly confidence: number
  readonly invalidation: string
}

export const confirmedMetadataSchema = z.object({
  symbol: z.string(),
  provider: z.string(),
  provider_symbol: z.string(),
  market_div_code: z.string(),
  timeframe: z.string(),
  trade_date: z.string(),
  decision_time_exchange: z.string(),
  exchange_tz: z.string(),
  price_basis: z.string(),
  session_state: z.string(),
  provider_status: z.enum(providerStatusValues),
  scenario: z.string(),
  confidence: z.number(),
  invalidation: z.string(),
})

export type CapturePayload = {
  readonly screenshot_data_url: string
  readonly extracted: ExtractedMetadata
  readonly confirmed: ConfirmedMetadata
  readonly decision: Decision
  readonly notes: string
  readonly warnings: readonly WarningCode[]
}

export type CaptureDraftPayload = Omit<CapturePayload, "screenshot_data_url">

export const captureDraftPayloadSchema = z.object({
  extracted: extractedMetadataSchema,
  confirmed: confirmedMetadataSchema,
  decision: z.enum(decisionValues),
  notes: z.string(),
  warnings: z.array(z.enum(warningValues)),
})

export const capturePayloadSchema = captureDraftPayloadSchema.extend({
  screenshot_data_url: z.string(),
})

export const captureResponseSchema = z.object({
  capture: z.object({
    id: z.string(),
    created_at: z.string(),
    screenshot_sha256: z.string(),
    screenshot_path: z.string(),
    confirmed: z.object({
      symbol: z.string(),
      timeframe: z.string(),
      trade_date: z.string(),
    }),
    warnings: z.array(z.enum(warningValues)),
  }),
})

export type CaptureResponse = z.infer<typeof captureResponseSchema>

export type CheckHealthMessage = {
  readonly kind: "check-health"
  readonly settings: ExtensionSettings
}

export type SaveCaptureMessage = {
  readonly kind: "save-capture"
  readonly settings: ExtensionSettings
  readonly payload: CaptureDraftPayload
}

export type RetryCaptureMessage = {
  readonly kind: "retry-capture"
  readonly settings: ExtensionSettings
  readonly payload: CapturePayload
}

export type CaptureMessage = CheckHealthMessage | SaveCaptureMessage | RetryCaptureMessage

export type HealthMessageResponse =
  | { readonly ok: true; readonly status: number }
  | { readonly ok: false; readonly error: string }

export type SaveCaptureMessageResponse =
  | { readonly ok: true; readonly id: string; readonly warnings: readonly WarningCode[] }
  | { readonly ok: false; readonly error: string; readonly retry_payload?: CapturePayload | undefined }

export const healthMessageResponseSchema = z.discriminatedUnion("ok", [
  z.object({ ok: z.literal(true), status: z.number() }),
  z.object({ ok: z.literal(false), error: z.string() }),
])

export const saveCaptureMessageResponseSchema = z.discriminatedUnion("ok", [
  z.object({ ok: z.literal(true), id: z.string(), warnings: z.array(z.enum(warningValues)) }),
  z.object({ ok: z.literal(false), error: z.string(), retry_payload: capturePayloadSchema.optional() }),
])

export const extensionMessageSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("check-health"),
    settings: z.object({ apiBaseUrl: z.string(), apiToken: z.string() }),
  }),
  z.object({
    kind: z.literal("save-capture"),
    settings: z.object({ apiBaseUrl: z.string(), apiToken: z.string() }),
    payload: captureDraftPayloadSchema,
  }),
  z.object({
    kind: z.literal("retry-capture"),
    settings: z.object({ apiBaseUrl: z.string(), apiToken: z.string() }),
    payload: capturePayloadSchema,
  }),
])

export type ExtensionSettings = {
  readonly apiBaseUrl: string
  readonly apiToken: string
}
