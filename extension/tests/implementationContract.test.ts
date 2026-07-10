import { describe, expect, test } from "bun:test"

import { REVIEW_HTTP_TIMEOUT } from "../src/backgroundCapture"

const source = async (relativePath: string): Promise<string> =>
  Bun.file(new URL(relativePath, import.meta.url)).text()

const pureLoc = (text: string): number =>
  text.split("\n").filter((line) => {
    const trimmed = line.trim()
    return trimmed.length > 0 && !trimmed.startsWith("//")
  }).length

describe("extension implementation contract", () => {
  test("does not abandon a review before the bounded backend pipeline completes", async () => {
    // Given
    const background = await source("../src/background.ts")

    // When
    const configured = REVIEW_HTTP_TIMEOUT

    // Then
    expect(configured).toBe(false)
    expect(background).toContain("timeout: REVIEW_HTTP_TIMEOUT")
  })

  test("acknowledges screenshot capture before posting the capture payload", async () => {
    // Given
    const background = await source("../src/background.ts")

    // When
    const captureIndex = background.indexOf("captureVisibleTab")
    const acknowledgementIndex = background.indexOf('kind: "screenshot-captured"')
    const postIndex = background.indexOf("postCapture(capturePayload")

    // Then
    expect(captureIndex).toBeGreaterThanOrEqual(0)
    expect(acknowledgementIndex).toBeGreaterThan(captureIndex)
    expect(postIndex).toBeGreaterThan(acknowledgementIndex)
  })

  test("keeps the content entry module below 250 pure lines", async () => {
    // Given
    const content = await source("../src/content.ts")

    // When
    const lines = pureLoc(content)

    // Then
    expect(lines).toBeLessThanOrEqual(250)
  })

  test("does not use an inset shadow for selected hypotheses", async () => {
    // Given
    const actions = await source("../src/actions.css")

    // When
    const selectedRule = actions.match(/\.fj-segments button\[data-selected="true"\][\s\S]*?\}/u)?.[0] ?? ""

    // Then
    expect(selectedRule).not.toContain("box-shadow: inset")
  })

  test("does not ship visible legacy capture controls", async () => {
    // Given
    const markup = `${await source("../src/content.ts")}\n${await source("../preview.html")}`
    const prohibited = [
      "data-decision=",
      "data-save-draft",
      "data-copy-payload",
      "data-retry-capture",
      ">Long<",
      ">Short<",
      ">Watch<",
      ">Skip<",
    ]

    // When
    const found = prohibited.filter((token) => markup.includes(token))

    // Then
    expect(found).toEqual([])
  })

  test("records review and hypothesis primitives as implemented", async () => {
    // Given
    const design = await source("../../DESIGN.md")

    // When
    const staleLedger = design.includes("Motion and review content are not implemented")

    // Then
    expect(staleLedger).toBe(false)
  })

  test("uses natural CJK wrapping with an emergency overflow fallback", async () => {
    // Given
    const actions = await source("../src/actions.css")

    // When
    const hasNaturalWrapping = actions.includes("word-break: keep-all")
    const hasOverflowFallback = actions.includes("overflow-wrap: anywhere")

    // Then
    expect(hasNaturalWrapping).toBe(true)
    expect(hasOverflowFallback).toBe(true)
  })

  test("reduces the mobile decision note by at least 20 pixels", async () => {
    // Given
    const actions = await source("../src/actions.css")

    // When
    const hasCompactMobileNote = actions.includes(".fj-root textarea") && actions.includes("min-height: 44px")

    // Then
    expect(hasCompactMobileNote).toBe(true)
  })
})
