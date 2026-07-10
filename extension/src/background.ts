import ky from "ky"

import { attachScreenshot, failedCaptureResponse } from "./backgroundCapture"
import { captureResponseSchema, extensionMessageSchema } from "./types"
import type {
  CapturePayload,
  HealthMessageResponse,
  SaveCaptureMessageResponse,
} from "./types"

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

const requireActiveTradingViewSender = async (sender: chrome.runtime.MessageSender): Promise<number> => {
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
  return tab.windowId
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
      timeout: 5_000,
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
  payload: Omit<CapturePayload, "screenshot_data_url">,
  apiBaseUrl: string,
  apiToken: string,
  windowId: number,
): Promise<SaveCaptureMessageResponse> => {
  requireLoopback(apiBaseUrl)
  const screenshotDataUrl = await captureVisibleTab(windowId)
  const capturePayload = attachScreenshot(payload, screenshotDataUrl)
  try {
    return await postCapture(capturePayload, apiBaseUrl, apiToken)
  } catch (error) {
    if (error instanceof Error) {
      return failedCaptureResponse(error, capturePayload)
    }
    throw error
  }
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
            ),
          )
          return
        case "retry-capture":
          sendResponse(await retryCapture(parsed.data.payload, settings.apiBaseUrl, settings.apiToken))
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
