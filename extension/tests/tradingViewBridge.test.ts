import { describe, expect, test } from "bun:test"

import {
  PAGE_BARS_EVENT,
  PAGE_BARS_PROGRESS_EVENT,
  PAGE_BARS_REQUEST_EVENT,
  PAGE_METADATA_EVENT,
  PAGE_METADATA_REQUEST_EVENT,
} from "../src/bridgeProtocol"
import { requestFreshPageMetadata, requestPageBars } from "../src/tradingViewBridge"

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

describe("TradingView bars request bridge", () => {
  test("requests full history and keeps waiting while progress arrives", async () => {
    // Given
    const events = installEventBridge()
    const progressSeen: number[] = []
    events.addEventListener(PAGE_BARS_REQUEST_EVENT, (event) => {
      if (!(event instanceof CustomEvent)) {
        return
      }
      expect(event.detail.fullHistory).toBe(true)
      const requestId = event.detail.requestId as string
      setTimeout(() => {
        events.dispatchEvent(
          new CustomEvent(PAGE_BARS_PROGRESS_EVENT, {
            detail: { requestId, loadedBars: 1_200 },
          }),
        )
      }, 15)
      setTimeout(() => {
        events.dispatchEvent(
          new CustomEvent(PAGE_BARS_EVENT, {
            detail: {
              requestId,
              symbol: "KRX_DLY:214450",
              timeframe: "240",
              columns: ["time", "open", "high", "low", "close", "volume"],
              rows: [[1_783_564_200, 1, 2, 0.5, 1.5, 100]],
              error: null,
            },
          }),
        )
      }, 30)
    })

    // When
    const bars = await requestPageBars({
      fullHistory: true,
      timeoutMs: 20,
      onProgress: (loadedBars) => progressSeen.push(loadedBars),
    })

    // Then: the 30ms answer outlives the 20ms idle timeout only because the
    // 15ms progress event re-armed it.
    expect(progressSeen).toEqual([1_200])
    expect(bars?.rows).toEqual([[1_783_564_200, 1, 2, 0.5, 1.5, 100]])
  })
})
