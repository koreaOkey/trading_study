import { describe, expect, test } from "bun:test"

import { bindOverlayResizeReclamp, clampOverlayPosition } from "../src/drag"

describe("draggable overlay bounds", () => {
  test("keeps the entire overlay inside the viewport", () => {
    // Given
    const position = { x: 500, y: -20 }
    const overlay = { width: 320, height: 400 }
    const viewport = { width: 600, height: 500 }

    // When
    const clamped = clampOverlayPosition(position, overlay, viewport, 8)

    // Then
    expect(clamped).toEqual({ x: 272, y: 8 })
  })

  test("reclamps a dragged overlay when review content increases its height", () => {
    // Given
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: { innerWidth: 600, innerHeight: 500 },
    })
    let height = 100
    let resize: (() => void) | null = null
    const classes = new Set(["fj-positioned"])
    const root = {
      classList: {
        add: (value: string) => classes.add(value),
        contains: (value: string) => classes.has(value),
      },
      style: { left: "100px", top: "350px", right: "auto", bottom: "auto" },
      getBoundingClientRect: () => ({ left: 100, top: 350, width: 320, height }),
    }
    bindOverlayResizeReclamp(root as HTMLElement, (callback) => {
      resize = callback
      return { observe: () => undefined }
    })

    // When
    height = 200
    resize?.()

    // Then
    expect(root.style.top).toBe("292px")
  })
})
