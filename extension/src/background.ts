import ky from "ky"
import { z } from "zod"

import {
  captureAndPost,
  failedCaptureResponse,
  REVIEW_HTTP_TIMEOUT,
} from "./backgroundCapture"
import {
  barSeriesCoverageSchema,
  extensionMessageSchema,
  reviewHistoryItemSchema,
} from "./messageProtocol"
import type {
  BarCoverageMessageResponse,
  HealthMessageResponse,
  RecentReviewsMessageResponse,
  RegisterBarSeriesMessageResponse,
  ReviewCaptureMessageResponse,
  SaveCaptureMessageResponse,
} from "./messageProtocol"
import { captureResponseSchema, decisionReviewResultSchema } from "./types"
import type { CapturePayload, DistributiveOmit } from "./types"

const isLoopbackUrl = (rawUrl: string): boolean => {
  try {
    const url = new URL(rawUrl)
    return (
      url.protocol === "http:" &&
      (url.hostname === "127.0.0.1" || url.hostname === "localhost")
    )
  } catch (error) {
    if (error instanceof TypeError) {
      return false
    }
    throw error
  }
}

const requireLoopback = (apiBaseUrl: string): void => {
  if (!isLoopbackUrl(apiBaseUrl)) {
    throw new Error("api_base_url_must_be_loopback")
  }
}

const isTradingViewUrl = (rawUrl: string | undefined): boolean => {
  if (rawUrl === undefined) {
    return false
  }
  try {
    const url = new URL(rawUrl)
    return url.protocol === "https:" && (
      url.hostname === "tradingview.com" || url.hostname.endsWith(".tradingview.com")
    )
  } catch (error) {
    if (error instanceof TypeError) {
      return false
    }
    throw error
  }
}

type CaptureSenderTarget = {
  readonly tabId: number
  readonly windowId: number
}

const requireActiveTradingViewSender = async (
  sender: chrome.runtime.MessageSender,
): Promise<CaptureSenderTarget> => {
  const tab = sender.tab
  if (
    tab?.id === undefined ||
    tab.windowId === undefined ||
    (sender.frameId !== undefined && sender.frameId !== 0) ||
    !isTradingViewUrl(sender.url ?? tab.url)
  ) {
    throw new Error("capture_sender_must_be_top_level_tradingview_tab")
  }
  const activeTabs = await chrome.tabs.query({ active: true, windowId: tab.windowId })
  if (activeTabs.length !== 1 || activeTabs[0]?.id !== tab.id) {
    throw new Error("capture_sender_tab_is_not_active")
  }
  return { tabId: tab.id, windowId: tab.windowId }
}

const captureVisibleTab = async (windowId: number): Promise<string> => {
  return new Promise((resolve, reject) => {
    chrome.tabs.captureVisibleTab(windowId, { format: "png" }, (dataUrl) => {
      const runtimeError = chrome.runtime.lastError
      if (runtimeError?.message !== undefined) {
        reject(new Error(runtimeError.message))
        return
      }
      if (dataUrl === undefined) {
        reject(new Error("capture_empty"))
        return
      }
      resolve(dataUrl)
    })
  })
}

const headersFor = (apiToken: string): Headers => {
  const headers = new Headers({ "Content-Type": "application/json" })
  if (apiToken.length > 0) {
    headers.set("Authorization", `Bearer ${apiToken}`)
  }
  return headers
}

const checkHealth = async (apiBaseUrl: string): Promise<HealthMessageResponse> => {
  requireLoopback(apiBaseUrl)
  const response = await ky.get(`${apiBaseUrl}/health`, {
    retry: { limit: 1 },
    throwHttpErrors: false,
    timeout: 3_000,
  })
  return { ok: true, status: response.status }
}

const postCapture = async (
  payload: CapturePayload,
  apiBaseUrl: string,
  apiToken: string,
): Promise<SaveCaptureMessageResponse> => {
  const rawResponse = await ky
    .post(`${apiBaseUrl}/api/captures`, {
      headers: headersFor(apiToken),
      json: payload,
      retry: { limit: 1 },
      // Multi-MB PNG screenshots can take >5s when the loopback port is an
      // SSH tunnel over a relayed (DERP) Tailscale link — keep this generous.
      timeout: 60_000,
    })
    .json<unknown>()
  const parsed = captureResponseSchema.parse(rawResponse)
  return {
    ok: true,
    id: parsed.capture.id,
    warnings: parsed.capture.warnings,
  }
}

const saveCapture = async (
  payload: DistributiveOmit<CapturePayload, "screenshot_data_url">,
  apiBaseUrl: string,
  apiToken: string,
  target: CaptureSenderTarget,
  captureRequestId: string,
): Promise<SaveCaptureMessageResponse> => {
  requireLoopback(apiBaseUrl)
  return captureAndPost(payload, {
    captureScreenshot: () => captureVisibleTab(target.windowId),
    acknowledgeScreenshot: async () => {
      await chrome.tabs.sendMessage(target.tabId, { kind: "screenshot-captured", captureRequestId })
    },
    postCapture: (capturePayload) => postCapture(capturePayload, apiBaseUrl, apiToken),
  })
}

const retryCapture = async (
  payload: CapturePayload,
  apiBaseUrl: string,
  apiToken: string,
): Promise<SaveCaptureMessageResponse> => {
  requireLoopback(apiBaseUrl)
  try {
    return await postCapture(payload, apiBaseUrl, apiToken)
  } catch (error) {
    if (error instanceof Error) {
      return failedCaptureResponse(error, payload)
    }
    throw error
  }
}

const registerBarSeriesResponseSchema = z.object({
  coverage: barSeriesCoverageSchema,
  reviews: z.array(decisionReviewResultSchema),
})

const barCoverageResponseSchema = z.object({
  registered: z.boolean(),
  coverage: barSeriesCoverageSchema.nullable(),
})

const registerBarSeries = async (
  symbol: string,
  timeframe: string,
  csvText: string,
  apiBaseUrl: string,
  apiToken: string,
): Promise<RegisterBarSeriesMessageResponse> => {
  requireLoopback(apiBaseUrl)
  const rawResponse = await ky
    .post(`${apiBaseUrl}/api/bar-series`, {
      headers: headersFor(apiToken),
      json: { symbol, timeframe, csv_text: csvText },
      retry: { limit: 0 },
      // Registration triggers deferred Hermes reviews server-side; a session
      // with several judgments can legitimately take minutes.
      timeout: REVIEW_HTTP_TIMEOUT,
    })
    .json<unknown>()
  const parsed = registerBarSeriesResponseSchema.parse(rawResponse)
  return { ok: true, coverage: parsed.coverage, reviews: parsed.reviews }
}

const getBarCoverage = async (
  symbol: string,
  timeframe: string,
  apiBaseUrl: string,
  apiToken: string,
): Promise<BarCoverageMessageResponse> => {
  requireLoopback(apiBaseUrl)
  const rawResponse = await ky
    .get(`${apiBaseUrl}/api/bar-series/coverage`, {
      headers: headersFor(apiToken),
      searchParams: { symbol, timeframe },
      retry: { limit: 1 },
      timeout: 5_000,
    })
    .json<unknown>()
  const parsed = barCoverageResponseSchema.parse(rawResponse)
  return { ok: true, registered: parsed.registered, coverage: parsed.coverage }
}

const recentReviewsResponseSchema = z.object({
  items: z.array(reviewHistoryItemSchema),
})

const getRecentReviews = async (
  symbol: string,
  limit: number,
  apiBaseUrl: string,
  apiToken: string,
): Promise<RecentReviewsMessageResponse> => {
  requireLoopback(apiBaseUrl)
  const rawResponse = await ky
    .get(`${apiBaseUrl}/api/reviews`, {
      headers: headersFor(apiToken),
      searchParams: { symbol, limit },
      retry: { limit: 1 },
      timeout: 10_000,
    })
    .json<unknown>()
  return { ok: true, items: recentReviewsResponseSchema.parse(rawResponse).items }
}

const reviewCapture = async (
  captureId: string,
  apiBaseUrl: string,
  apiToken: string,
): Promise<ReviewCaptureMessageResponse> => {
  requireLoopback(apiBaseUrl)
  const rawResponse = await ky
    .post(`${apiBaseUrl}/api/captures/${encodeURIComponent(captureId)}/ai-review`, {
      headers: headersFor(apiToken),
      retry: { limit: 0 },
      timeout: REVIEW_HTTP_TIMEOUT,
    })
    .json<unknown>()
  return { ok: true, result: decisionReviewResultSchema.parse(rawResponse) }
}

const assertNever = (value: never): never => {
  throw new Error(`Unhandled message kind: ${String(value)}`)
}

chrome.runtime.onMessage.addListener((message: unknown, sender, sendResponse) => {
  const parsed = extensionMessageSchema.safeParse(message)
  if (!parsed.success) {
    return false
  }
  void (async (): Promise<void> => {
    try {
      const { settings } = parsed.data
      switch (parsed.data.kind) {
        case "check-health":
          sendResponse(await checkHealth(settings.apiBaseUrl))
          return
        case "save-capture":
          sendResponse(
            await saveCapture(
              parsed.data.payload,
              settings.apiBaseUrl,
              settings.apiToken,
              await requireActiveTradingViewSender(sender),
              parsed.data.captureRequestId,
            ),
          )
          return
        case "retry-capture":
          sendResponse(await retryCapture(parsed.data.payload, settings.apiBaseUrl, settings.apiToken))
          return
        case "review-capture":
          sendResponse(
            await reviewCapture(
              parsed.data.captureId,
              settings.apiBaseUrl,
              settings.apiToken,
            ),
          )
          return
        case "register-bar-series":
          sendResponse(
            await registerBarSeries(
              parsed.data.symbol,
              parsed.data.timeframe,
              parsed.data.csvText,
              settings.apiBaseUrl,
              settings.apiToken,
            ),
          )
          return
        case "get-bar-coverage":
          sendResponse(
            await getBarCoverage(
              parsed.data.symbol,
              parsed.data.timeframe,
              settings.apiBaseUrl,
              settings.apiToken,
            ),
          )
          return
        case "get-recent-reviews":
          sendResponse(
            await getRecentReviews(
              parsed.data.symbol,
              parsed.data.limit,
              settings.apiBaseUrl,
              settings.apiToken,
            ),
          )
          return
        default:
          assertNever(parsed.data)
      }
    } catch (error) {
      if (error instanceof Error) {
        sendResponse({ ok: false, error: error.message })
        return
      }
      throw error
    }
  })()
  return true
})

chrome.action.onClicked.addListener((tab) => {
  if (tab.id !== undefined) {
    void chrome.tabs.sendMessage(tab.id, { kind: "open-sheet" })
  }
})
