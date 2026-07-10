import { describe, expect, test } from "bun:test"

import { renderReview, renderReviewError } from "../src/reviewRenderer"
import type { DecisionReviewResult } from "../src/types"

class FakeElement {
  className = ""
  textContent = ""
  hidden = false
  readonly children: FakeElement[] = []
  readonly attributes = new Map<string, string>()
  offsetTop = 0
  scrollTop = 0

  replaceChildren(...children: FakeElement[]): void {
    this.children.splice(0, this.children.length, ...children)
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value)
  }

  removeAttribute(name: string): void {
    this.attributes.delete(name)
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null
  }
}

class FakeRoot {
  readonly container = new FakeElement()
  readonly section = new FakeElement()
  readonly retry = new FakeElement()
  readonly scroller = new FakeElement()

  querySelector(selector: string): FakeElement | null {
    switch (selector) {
      case "[data-review]":
        return this.container
      case "[data-review-section]":
        return this.section
      case "[data-retry-review]":
        return this.retry
      case ".fj-sheet-scroll":
        return this.scroller
      default:
        return null
    }
  }
}

const flattenText = (element: FakeElement): readonly string[] => [
  element.textContent,
  ...element.children.flatMap(flattenText),
]

describe("decision review rendering", () => {
  test("reveals a ready review inside the sheet scroll region", () => {
    // Given
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { createElement: () => new FakeElement() },
    })
    const root = new FakeRoot()
    root.section.offsetTop = 480
    const result: DecisionReviewResult = {
      schema_version: "decision_review_result.v1",
      capture_id: "capture-1",
      status: "ready",
      evidence: null,
      review: {
        schema_version: "decision_review.v1",
        review_created_at_utc: "2026-07-09T02:31:00Z",
        review_model: "hermes-model",
        review_profile: "trading",
        overall_assessment: "balanced",
        summary: "Review complete.",
        sufficient_evidence: [],
        missing_evidence: [],
        excessive_evidence: [],
        contradictions: [],
        revised_decision_note: "Wait for confirmation.",
        risk_note: "Crossovers can fail.",
      },
      failure: null,
    }

    // When
    renderReview(root as HTMLElement, result)

    // Then
    expect(root.scroller.scrollTop).toBe(480)
    expect(root.section.getAttribute("role")).toBe("status")
    expect(root.section.getAttribute("aria-live")).toBe("polite")
    const text = flattenText(root.container)
    expect(text).toContain("Overall assessment")
    expect(text).toContain("Sufficient evidence")
    expect(text).toContain("Missing evidence")
    expect(text).toContain("Excessive / redundant evidence")
    expect(text).toContain("Contradictions")
    expect(text).toContain("Revised decision note")
    expect(text).toContain("Risk note")
    expect(text).toContain("Model metadata")
    expect(text.filter((value) => value === "None identified")).toHaveLength(4)
  })

  test("announces and reveals a review failure", () => {
    // Given
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { createElement: () => new FakeElement() },
    })
    const root = new FakeRoot()
    root.section.offsetTop = 620

    // When
    renderReviewError(root as HTMLElement, "Hermes unavailable")

    // Then
    expect(root.scroller.scrollTop).toBe(620)
    expect(root.section.getAttribute("role")).toBe("alert")
    expect(root.section.getAttribute("aria-live")).toBe("assertive")
  })

  test("keeps malformed agent strings as text nodes", () => {
    // Given
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { createElement: () => new FakeElement() },
    })
    const malicious = '<img src=x onerror="globalThis.pwned=true">'
    const result: DecisionReviewResult = {
      schema_version: "decision_review_result.v1",
      capture_id: "capture-1",
      status: "ready",
      evidence: null,
      review: {
        schema_version: "decision_review.v1",
        review_created_at_utc: "2026-07-09T02:31:00Z",
        review_model: "hermes-model",
        review_profile: "trading",
        overall_assessment: "conflicted",
        summary: malicious,
        sufficient_evidence: [malicious],
        missing_evidence: [],
        excessive_evidence: [],
        contradictions: [],
        revised_decision_note: malicious,
        risk_note: malicious,
      },
      failure: null,
    }
    const root = new FakeRoot()

    // When
    renderReview(root as HTMLElement, result)

    // Then
    expect(flattenText(root.container).filter((text) => text === malicious)).toHaveLength(4)
    expect(Reflect.get(globalThis, "pwned")).toBeUndefined()
  })
})
