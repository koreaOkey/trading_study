import {
  healthMessageResponseSchema,
  reviewCaptureMessageResponseSchema,
  saveCaptureMessageResponseSchema,
} from "./messageProtocol"
import type {
  HealthMessageResponse,
  ReviewCaptureMessageResponse,
  SaveCaptureMessageResponse,
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
