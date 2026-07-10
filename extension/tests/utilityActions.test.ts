import { describe, expect, test } from "bun:test"

import { bindUtilityActionButtons } from "../src/utilityActions"
import type { UtilityActionWorkflow } from "../src/utilityActions"

class FakeButton {
  private clickListener: ((event: MouseEvent) => void) | null = null

  addEventListener(type: "click", listener: (event: MouseEvent) => void): void {
    expect(type).toBe("click")
    this.clickListener = listener
  }

  click(isTrusted: boolean): void {
    this.clickListener?.({ isTrusted } as MouseEvent)
  }
}

class FakeRoot {
  readonly saveDraft = new FakeButton()
  readonly retry = new FakeButton()
  readonly copyPayload = new FakeButton()

  querySelector(selector: string): FakeButton | null {
    switch (selector) {
      case "[data-save-draft]":
        return this.saveDraft
      case "[data-retry-capture]":
        return this.retry
      case "[data-copy-payload]":
        return this.copyPayload
      default:
        return null
    }
  }
}

describe("utility action buttons", () => {
  test("dispatches each utility button to the matching workflow action", () => {
    // Given
    const calls: string[] = []
    const root = new FakeRoot()
    const workflow: UtilityActionWorkflow = {
      saveDraftAction: async () => {
        calls.push("save-draft")
      },
      retry: async () => {
        calls.push("retry")
      },
      copyPayload: async () => {
        calls.push("copy-payload")
      },
    }

    // When
    bindUtilityActionButtons(root, workflow)
    root.saveDraft.click(true)
    root.retry.click(true)
    root.copyPayload.click(true)

    // Then
    expect(calls).toEqual(["save-draft", "retry", "copy-payload"])
  })

  test("ignores synthetic utility clicks from the host page", () => {
    // Given
    const calls: string[] = []
    const root = new FakeRoot()
    const workflow: UtilityActionWorkflow = {
      saveDraftAction: async () => { calls.push("save-draft") },
      retry: async () => { calls.push("retry") },
      copyPayload: async () => { calls.push("copy-payload") },
    }

    // When
    bindUtilityActionButtons(root, workflow)
    root.saveDraft.click(false)
    root.retry.click(false)
    root.copyPayload.click(false)

    // Then
    expect(calls).toEqual([])
  })
})
