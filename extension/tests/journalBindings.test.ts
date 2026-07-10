import { describe, expect, test } from "bun:test"

import { bindDraftAutosave, handleJournalKeydown } from "../src/journalBindings"

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
})
