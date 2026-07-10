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
  readonly submitReview = new FakeButton()
  readonly retryReview = new FakeButton()

  querySelector(selector: string): FakeButton | null {
    switch (selector) {
      case "[data-submit-review]":
        return this.submitReview
      case "[data-retry-review]":
        return this.retryReview
      default:
        return null
    }
  }
}

describe("utility action buttons", () => {
  test("dispatches the submit and capture-id retry buttons", () => {
    // Given
    const calls: string[] = []
    const root = new FakeRoot()
    const workflow: UtilityActionWorkflow = {
      submit: async () => {
        calls.push("submit")
      },
      retryReview: async () => {
        calls.push("retry-review")
      },
    }

    // When
    bindUtilityActionButtons(root, workflow)
    root.submitReview.click(true)
    root.retryReview.click(true)

    // Then
    expect(calls).toEqual(["submit", "retry-review"])
  })

  test("ignores synthetic utility clicks from the host page", () => {
    // Given
    const calls: string[] = []
    const root = new FakeRoot()
    const workflow: UtilityActionWorkflow = {
      submit: async () => { calls.push("submit") },
      retryReview: async () => { calls.push("retry-review") },
    }

    // When
    bindUtilityActionButtons(root, workflow)
    root.submitReview.click(false)
    root.retryReview.click(false)

    // Then
    expect(calls).toEqual([])
  })
})
