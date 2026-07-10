import type {
  CaptureDraftPayload,
  CapturePayload,
} from "./types"
import type { SaveCaptureMessageResponse } from "./messageProtocol"

export const REVIEW_HTTP_TIMEOUT = false as const

type CaptureSubmissionDependencies = {
  readonly captureScreenshot: () => Promise<string>
  readonly acknowledgeScreenshot: () => Promise<void>
  readonly postCapture: (payload: CapturePayload) => Promise<SaveCaptureMessageResponse>
}

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

export const captureAndPost = async (
  payload: CaptureDraftPayload,
  dependencies: CaptureSubmissionDependencies,
): Promise<SaveCaptureMessageResponse> => {
  const capturePayload = attachScreenshot(payload, await dependencies.captureScreenshot())
  await dependencies.acknowledgeScreenshot()
  try {
    return await dependencies.postCapture(capturePayload)
  } catch (error) {
    if (error instanceof Error) {
      return failedCaptureResponse(error, capturePayload)
    }
    throw error
  }
}
