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

export type CaptureMessage =
  | CheckHealthMessage
  | SaveCaptureMessage
  | RetryCaptureMessage
  | ReviewCaptureMessage

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
])
