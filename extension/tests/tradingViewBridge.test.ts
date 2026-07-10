import { describe, expect, test } from "bun:test"

import {
  PAGE_METADATA_EVENT,
  PAGE_METADATA_REQUEST_EVENT,
} from "../src/bridgeProtocol"
import { requestFreshPageMetadata } from "../src/tradingViewBridge"

const installEventBridge = (): EventTarget => {
  const eventTarget = new EventTarget()
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: eventTarget,
  })
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      clearTimeout,
      setTimeout,
    },
  })
  return eventTarget
}

describe("TradingView metadata request bridge", () => {
  test("waits for the response correlated to the capture request", async () => {
    // Given
    const events = installEventBridge()
    events.addEventListener(PAGE_METADATA_REQUEST_EVENT, (event) => {
      if (!(event instanceof CustomEvent)) {
        return
      }
      events.dispatchEvent(new CustomEvent(PAGE_METADATA_EVENT, {
        detail: {
          symbol: "KRX_DLY:214450",
          timeframe: "5",
          replayActive: true,
          replayTimestamp: 1_783_564_200,
          requestId: "stale-request",
        },
      }))
      events.dispatchEvent(new CustomEvent(PAGE_METADATA_EVENT, {
        detail: {
          symbol: "KRX_DLY:214450",
          timeframe: "5",
          replayActive: true,
          replayTimestamp: 1_783_564_500,
          requestId: event.detail.requestId,
        },
      }))
    })

    // When
    const candidate = await requestFreshPageMetadata(100)

    // Then
    expect(candidate).toEqual({
      symbol: "214450",
      timeframe: "5",
      decisionTime: "2026-07-09T11:35:00+09:00",
      replayActive: true,
    })
  })
})
