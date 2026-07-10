import { describe, expect, test } from "bun:test"

import { clampOverlayPosition } from "../src/drag"

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
})
