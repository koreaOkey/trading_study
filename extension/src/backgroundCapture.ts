import type {
  CaptureDraftPayload,
  CapturePayload,
  SaveCaptureMessageResponse,
} from "./types"

export const attachScreenshot = (
  payload: CaptureDraftPayload,
  screenshotDataUrl: string,
): CapturePayload => ({
  ...payload,
  screenshot_data_url: screenshotDataUrl,
})

export const failedCaptureResponse = (
  error: Error,
  payload: CapturePayload,
): SaveCaptureMessageResponse => ({
  ok: false,
  error: error.message,
  retry_payload: payload,
})
