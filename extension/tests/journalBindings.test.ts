import { describe, expect, test } from "bun:test"

import {
  bindDraftAutosave,
  guardOverlayKeydown,
  handleJournalKeydown,
  overlayOwnsEvent,
} from "../src/journalBindings"

class FakeField {
  private inputListener: ((event: Event) => void) | null = null

  addEventListener(type: string, listener: (event: Event) => void): void {
    if (type === "input") this.inputListener = listener
  }

  input(isTrusted: boolean): void {
    this.inputListener?.({ isTrusted } as Event)
  }
}

class FakeStatus {
  textContent = ""
  readonly dataset: Record<string, string> = {}
}

class FakeAutosaveRoot {
  readonly field = new FakeField()
  readonly status = new FakeStatus()

  querySelector(selector: string): FakeStatus | null {
    return selector === "[data-draft-status]" ? this.status : null
  }

  querySelectorAll(): readonly FakeField[] {
    return [this.field]
  }
}

describe("journal input bindings", () => {
  test("autosaves 400ms after a trusted input event", async () => {
    // Given
    const root = new FakeAutosaveRoot()
    let callback: (() => void) | null = null
    let delayMs = 0
    let saves = 0
    bindDraftAutosave(root as HTMLElement, {
      save: async () => {
        saves += 1
      },
      scheduleTimer: (scheduled, delay) => {
        callback = scheduled
        delayMs = delay
        return 1
      },
      clearTimer: () => undefined,
    })

    // When
    root.field.input(true)
    callback?.()
    await Promise.resolve()

    // Then
    expect(delayMs).toBe(400)
    expect(saves).toBe(1)
    expect(root.status.dataset["draftState"]).toBe("saved")
  })

  test("submits on Ctrl+Enter while the journal is open", () => {
    // Given
    let submissions = 0
    let prevented = false
    const root = {
      classList: { contains: (value: string) => value === "fj-sheet-open" },
      querySelector: () => ({ disabled: false }),
    }
    const event = {
      isTrusted: true,
      metaKey: false,
      ctrlKey: true,
      shiftKey: false,
      key: "Enter",
      preventDefault: () => {
        prevented = true
      },
    }

    // When
    handleJournalKeydown(event, root as HTMLElement, {
      submit: async () => {
        submissions += 1
      },
    })

    // Then
    expect(submissions).toBe(1)
    expect(prevented).toBe(true)
  })

  test("overlay key guard stops propagation so page hotkeys never fire", () => {
    // Given: a plain character key pressed inside the overlay.
    let stopped = false
    const root = {
      classList: { contains: () => false },
      querySelector: () => null,
    }
    const event = {
      isTrusted: true,
      metaKey: false,
      ctrlKey: false,
      shiftKey: false,
      key: "1",
      preventDefault: () => {},
      stopPropagation: () => {
        stopped = true
      },
    }

    // When
    guardOverlayKeydown(event, root as HTMLElement, { submit: async () => {} })

    // Then: the event must not reach TradingView's document-level handlers.
    expect(stopped).toBe(true)
  })

  test("overlay key guard still submits on Ctrl+Enter", () => {
    // Given
    let submissions = 0
    let stopped = false
    const root = {
      classList: { contains: (value: string) => value === "fj-sheet-open" },
      querySelector: () => ({ disabled: false }),
    }
    const event = {
      isTrusted: true,
      metaKey: false,
      ctrlKey: true,
      shiftKey: false,
      key: "Enter",
      preventDefault: () => {},
      stopPropagation: () => {
        stopped = true
      },
    }

    // When
    guardOverlayKeydown(event, root as HTMLElement, {
      submit: async () => {
        submissions += 1
      },
    })

    // Then
    expect(submissions).toBe(1)
    expect(stopped).toBe(true)
  })

  test("window capture shield claims only events retargeted to the overlay host", () => {
    // Given: a closed shadow root retargets overlay events, so from window
    // the overlay is visible only as its host element in the composed path.
    const host = { id: "fj-host" } as unknown as HTMLElement
    const other = { id: "page-node" }
    const fromOverlay = { composedPath: () => [host, other] }
    const fromPage = { composedPath: () => [other] }

    // Then
    expect(overlayOwnsEvent(fromOverlay as unknown as Event, host)).toBe(true)
    expect(overlayOwnsEvent(fromPage as unknown as Event, host)).toBe(false)
  })
})
