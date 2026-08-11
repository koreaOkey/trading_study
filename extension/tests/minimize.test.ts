import { describe, expect, test } from "bun:test"

import {
  isOverlayMinimized,
  minimizeOverlay,
  restoreMinimizedPreference,
  restoreOverlay,
} from "../src/minimize"

class FakeRoot {
  private readonly classes: Set<string>
  readonly dataset: Record<string, string> = {}

  constructor(initial: readonly string[] = []) {
    this.classes = new Set(initial)
  }

  readonly classList = {
    add: (value: string): void => void this.classes.add(value),
    remove: (value: string): void => void this.classes.delete(value),
    contains: (value: string): boolean => this.classes.has(value),
  }
}

const withFakeWindow = (): void => {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { requestAnimationFrame: () => 0 },
  })
}

describe("overlay icon mode", () => {
  test("minimizing an open sheet remembers the sheet as the restore target", () => {
    // Given
    withFakeWindow()
    const root = new FakeRoot(["fj-sheet-open"])
    const persisted: unknown[] = []

    // When
    minimizeOverlay(root as unknown as HTMLElement, async (preference) => {
      persisted.push(preference)
    })

    // Then
    expect(root.classList.contains("fj-minimized")).toBe(true)
    expect(root.classList.contains("fj-sheet-open")).toBe(false)
    expect(root.dataset["minimizedFrom"]).toBe("sheet")
    expect(isOverlayMinimized(root as unknown as HTMLElement)).toBe(true)
    expect(persisted).toEqual([{ minimized: true, from: "sheet" }])
  })

  test("restoring reports the origin so a sheet-born icon reopens the sheet", () => {
    // Given
    withFakeWindow()
    const root = new FakeRoot(["fj-minimized"])
    root.dataset["minimizedFrom"] = "sheet"
    const persisted: unknown[] = []

    // When
    const origin = restoreOverlay(root as unknown as HTMLElement, async (preference) => {
      persisted.push(preference)
    })

    // Then
    expect(origin).toBe("sheet")
    expect(root.classList.contains("fj-minimized")).toBe(false)
    expect(root.dataset["minimizedFrom"]).toBeUndefined()
    expect(persisted).toEqual([{ minimized: false, from: "sheet" }])
  })

  test("restoring a dock-born icon returns to the dock", () => {
    // Given
    withFakeWindow()
    const root = new FakeRoot(["fj-minimized"])
    root.dataset["minimizedFrom"] = "dock"

    // When
    const origin = restoreOverlay(root as unknown as HTMLElement, async () => undefined)

    // Then
    expect(origin).toBe("dock")
    expect(root.classList.contains("fj-minimized")).toBe(false)
  })

  test("reapplies a stored icon preference, including its origin, on mount", async () => {
    // Given
    const minimizedRoot = new FakeRoot()
    const dockRoot = new FakeRoot()
    const legacyRoot = new FakeRoot()

    // When
    await restoreMinimizedPreference(minimizedRoot as unknown as HTMLElement, async () => ({
      minimized: true,
      from: "sheet",
    }))
    await restoreMinimizedPreference(dockRoot as unknown as HTMLElement, async () => ({
      minimized: false,
      from: "dock",
    }))
    await restoreMinimizedPreference(legacyRoot as unknown as HTMLElement, async () => null)

    // Then
    expect(minimizedRoot.classList.contains("fj-minimized")).toBe(true)
    expect(minimizedRoot.dataset["minimizedFrom"]).toBe("sheet")
    expect(dockRoot.classList.contains("fj-minimized")).toBe(false)
    expect(legacyRoot.classList.contains("fj-minimized")).toBe(false)
  })
})
