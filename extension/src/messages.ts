import { healthMessageResponseSchema, saveCaptureMessageResponseSchema } from "./types"
import type {
  CaptureDraftPayload,
  CapturePayload,
  ExtensionSettings,
  HealthMessageResponse,
  SaveCaptureMessageResponse,
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
): Promise<SaveCaptureMessageResponse> => {
  return saveCaptureMessageResponseSchema.parse(
    await chrome.runtime.sendMessage({ kind: "save-capture", settings, payload }),
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
