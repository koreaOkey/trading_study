import { z } from "zod"

const timezoneAwareIsoSchema = z
  .string()
  .min(1)
  .max(40)
  .refine(
    (value) => /T.*(?:Z|[+-]\d{2}:\d{2})$/u.test(value) && Number.isFinite(Date.parse(value)),
    "decision_time_must_include_timezone",
  )

export const decisionValues = ["long", "short", "skip", "watch"] as const
export type Decision = (typeof decisionValues)[number]

export const setupValues = ["ma_crossover"] as const
export type Setup = (typeof setupValues)[number]

export const hypothesisValues = [
  "golden_cross_expected",
  "dead_cross_expected",
  "uncertain",
] as const
export type Hypothesis = (typeof hypothesisValues)[number]

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
  readonly decision_time_candidate: string
  readonly replay_active: boolean
  readonly captured_at: string
}

export const extractedMetadataSchema = z.object({
  source_url: z.string().url().max(2_048),
  page_title: z.string().min(1).max(240),
  symbol_candidate: z.string().max(32),
  timeframe_candidate: z.string().max(16),
  decision_time_candidate: z.union([z.literal(""), timezoneAwareIsoSchema]).default(""),
  replay_active: z.boolean().default(false),
  captured_at: z.string().datetime({ offset: true }),
})

export type ConfirmedMetadata = {
  readonly symbol: string
  readonly provider_symbol: string
  readonly market_div_code: string
  readonly timeframe: string
  readonly decision_time_exchange: string
  readonly exchange_tz: string
  readonly provider_status: ProviderStatus
  readonly provider?: string
  readonly price_basis?: string
  readonly session_state?: string
  readonly scenario?: string
  readonly confidence?: number
  readonly invalidation?: string
}

export const confirmedMetadataSchema = z.object({
  symbol: z.string().min(1).max(32),
  provider_symbol: z.string().max(32),
  market_div_code: z.string().max(8),
  timeframe: z.string().min(1).max(16),
  decision_time_exchange: timezoneAwareIsoSchema,
  exchange_tz: z.string().max(64),
  provider_status: z.enum(providerStatusValues),
})

type CaptureDraftBase = {
  readonly extracted: ExtractedMetadata
  readonly confirmed: ConfirmedMetadata
  readonly warnings: readonly WarningCode[]
}

export type MaCrossoverCaptureDraftPayload = CaptureDraftBase & {
  readonly setup: Setup
  readonly hypothesis: Hypothesis
  readonly decision_note: string
}

export type LegacyCaptureDraftPayload = CaptureDraftBase & {
  readonly decision: Decision
  readonly notes?: string
}

export type CaptureDraftPayload = MaCrossoverCaptureDraftPayload | LegacyCaptureDraftPayload

export type CapturePayload = CaptureDraftPayload & {
  readonly screenshot_data_url: string
}

export type DistributiveOmit<Value, Keys extends PropertyKey> = Value extends unknown
  ? Omit<Value, Keys>
  : never

const maCrossoverCaptureDraftPayloadSchema = z.object({
  extracted: extractedMetadataSchema,
  confirmed: confirmedMetadataSchema,
  setup: z.enum(setupValues),
  hypothesis: z.enum(hypothesisValues),
  decision_note: z.string().max(2_000),
  warnings: z.array(z.enum(warningValues)).max(warningValues.length),
}).strict()

const legacyCaptureDraftPayloadSchema = z.object({
  extracted: extractedMetadataSchema,
  confirmed: confirmedMetadataSchema,
  decision: z.enum(decisionValues),
  notes: z.string().max(2_000).default(""),
  warnings: z.array(z.enum(warningValues)).max(warningValues.length),
}).strict()

export const captureDraftPayloadSchema = z.union([
  maCrossoverCaptureDraftPayloadSchema,
  legacyCaptureDraftPayloadSchema,
])

const screenshotDataUrlSchema = z.string().min(32).max(14_000_000)

export const capturePayloadSchema = z.union([
  maCrossoverCaptureDraftPayloadSchema.extend({ screenshot_data_url: screenshotDataUrlSchema }),
  legacyCaptureDraftPayloadSchema.extend({ screenshot_data_url: screenshotDataUrlSchema }),
])

export const captureResponseSchema = z.object({
  capture: z.object({
    id: z.string(),
    created_at: z.string(),
    screenshot_sha256: z.string(),
    screenshot_path: z.string(),
    confirmed: z.object({
      symbol: z.string(),
      timeframe: z.string(),
    }),
    warnings: z.array(z.enum(warningValues)),
  }),
})

export type CaptureResponse = z.infer<typeof captureResponseSchema>

export const evidenceDataStatusValues = ["ready", "partial", "unavailable"] as const
export const gapTrendValues = ["narrowing", "widening", "flat"] as const
export const reviewOverallAssessmentValues = [
  "insufficient",
  "balanced",
  "overconfirmed",
  "conflicted",
] as const
export const decisionReviewFailureCodeValues = [
  "evidence_unavailable",
  "hermes_unavailable",
  "hermes_timeout",
  "invalid_response",
] as const
export const decisionReviewProfile = "trading" as const
export const decisionReviewRiskNote =
  "기술적 분석은 확률적 시나리오 정리이며 수익 보장이나 개인화된 투자 지시가 아니다." as const

const nullableDecimalSchema = z.string().nullable()

export const indicatorMeasurementSchema = z.object({
  value: nullableDecimalSchema,
  previous_value: nullableDecimalSchema,
  slope_pct: nullableDecimalSchema,
  distance_from_close_pct: nullableDecimalSchema,
  bars_used: z.number().int().nonnegative(),
  null_reason: z.string().max(200).nullable(),
})

export const maCrossoverEvidenceSchema = z.object({
  schema_version: z.literal("ma_crossover_evidence.v1"),
  provider: z.string().min(1).max(24),
  provider_symbol: z.string().min(1).max(32),
  timeframe: z.string().min(1).max(16),
  decision_time_exchange: timezoneAwareIsoSchema,
  data_status: z.enum(evidenceDataStatusValues),
  bar_count: z.number().int().nonnegative(),
  last_bar_time_exchange: timezoneAwareIsoSchema.nullable(),
  close: nullableDecimalSchema,
  volume: nullableDecimalSchema,
  sma_50: indicatorMeasurementSchema,
  sma_200: indicatorMeasurementSchema,
  vwma_100: indicatorMeasurementSchema,
  sma_50_to_sma_200_gap_pct: nullableDecimalSchema,
  gap_trend: z.enum(gapTrendValues).nullable(),
  null_reasons: z.array(z.string()),
})

export const decisionReviewSchema = z.object({
  schema_version: z.literal("decision_review.v1"),
  review_created_at_utc: z.string().datetime({ offset: true }),
  review_model: z.string().min(1).max(120),
  review_profile: z.literal(decisionReviewProfile),
  overall_assessment: z.enum(reviewOverallAssessmentValues),
  summary: z.string().min(1).max(2_000),
  sufficient_evidence: z.array(z.string()),
  missing_evidence: z.array(z.string()),
  excessive_evidence: z.array(z.string()),
  contradictions: z.array(z.string()),
  revised_decision_note: z.string().max(2_000),
  risk_note: z.literal(decisionReviewRiskNote),
})

export const decisionReviewFailureSchema = z.object({
  code: z.enum(decisionReviewFailureCodeValues),
  message: z.string().min(1).max(500),
  retryable: z.boolean(),
  review_model: z.string().min(1).max(120),
  review_profile: z.string().min(1).max(120),
})

export const decisionReviewResultSchema = z.discriminatedUnion("status", [
  z.object({
    schema_version: z.literal("decision_review_result.v1"),
    capture_id: z.string().min(1),
    status: z.literal("ready"),
    evidence: maCrossoverEvidenceSchema.nullable(),
    review: decisionReviewSchema,
    failure: z.null(),
  }),
  z.object({
    schema_version: z.literal("decision_review_result.v1"),
    capture_id: z.string().min(1),
    status: z.literal("failed"),
    evidence: maCrossoverEvidenceSchema.nullable(),
    review: z.null(),
    failure: decisionReviewFailureSchema,
  }),
])

export type IndicatorMeasurement = Readonly<z.infer<typeof indicatorMeasurementSchema>>
export type MaCrossoverEvidence = Readonly<z.infer<typeof maCrossoverEvidenceSchema>>
export type DecisionReview = Readonly<z.infer<typeof decisionReviewSchema>>
export type DecisionReviewFailure = Readonly<z.infer<typeof decisionReviewFailureSchema>>
export type DecisionReviewResult = Readonly<z.infer<typeof decisionReviewResultSchema>>

export type ExtensionSettings = {
  readonly apiBaseUrl: string
  readonly apiToken: string
}
