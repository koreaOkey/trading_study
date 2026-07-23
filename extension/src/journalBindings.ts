import type { CaptureWorkflow } from "./captureWorkflow"
import { closeSheet, openSheet } from "./overlayView"
import { saveDraft } from "./storage"
import type { Hypothesis } from "./types"
import { bindUtilityActionButtons } from "./utilityActions"

const HYPOTHESES = ["golden_cross_expected", "dead_cross_expected", "uncertain"] as const
const AUTOSAVE_DELAY_MS = 400

export type DraftController = {
  readonly schedule: () => void
  readonly flush: () => Promise<void>
}

type DraftAutosaveDependencies = {
  readonly save: (root: HTMLElement) => Promise<void>
  readonly scheduleTimer: (callback: () => void, delayMs: number) => number
  readonly clearTimer: (timer: number) => void
}

const defaultAutosaveDependencies: DraftAutosaveDependencies = {
  save: saveDraft,
  scheduleTimer: (callback, delayMs) => window.setTimeout(callback, delayMs),
  clearTimer: (timer) => window.clearTimeout(timer),
}

export const bindDraftAutosave = (
  root: HTMLElement,
  dependencies: DraftAutosaveDependencies = defaultAutosaveDependencies,
): DraftController => {
  const status = root.querySelector<HTMLElement>("[data-draft-status]")
  let timer: number | null = null
  let revision = 0
  const setDraftStatus = (message: string, state: string): void => {
    if (status !== null) {
      status.textContent = message
      status.dataset["draftState"] = state
    }
  }
  const flush = async (): Promise<void> => {
    if (timer !== null) {
      dependencies.clearTimer(timer)
      timer = null
    }
    const currentRevision = revision
    setDraftStatus("저장 중…", "saving")
    try {
      await dependencies.save(root)
      if (currentRevision === revision) setDraftStatus("자동 저장됨", "saved")
    } catch (error) {
      if (error instanceof Error) {
        setDraftStatus("저장 실패", "error")
        return
      }
      throw error
    }
  }
  const schedule = (): void => {
    revision += 1
    setDraftStatus("변경 사항 저장 대기", "pending")
    if (timer !== null) dependencies.clearTimer(timer)
    timer = dependencies.scheduleTimer(() => void flush(), AUTOSAVE_DELAY_MS)
  }
  root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input:not([type=hidden]), textarea")
    .forEach((field) => field.addEventListener("input", (event) => event.isTrusted && schedule()))
  return { schedule, flush }
}

export const bindHypothesis = (root: HTMLElement, draft: DraftController): (() => void) => {
  const input = root.querySelector<HTMLInputElement>('[data-field="hypothesis"]')
  const buttons = root.querySelectorAll<HTMLButtonElement>("[data-hypothesis]")
  const sync = (): void => {
    const selected = input?.value ?? "uncertain"
    buttons.forEach((button) => {
      const isSelected = button.dataset["hypothesis"] === selected
      button.ariaPressed = String(isSelected)
      button.dataset["selected"] = String(isSelected)
    })
  }
  buttons.forEach((button) => {
    button.addEventListener("click", (event) => {
      if (!event.isTrusted || input === null) return
      const value = button.dataset["hypothesis"]
      const hypothesis = HYPOTHESES.find((candidate) => candidate === value)
      if (hypothesis === undefined) return
      input.value = hypothesis satisfies Hypothesis
      sync()
      draft.schedule()
    })
  })
  sync()
  return sync
}

export const bindSubmitValidity = (root: HTMLElement): (() => void) => {
  const submit = root.querySelector<HTMLButtonElement>("[data-submit-review]")
  const requiredFields = root.querySelectorAll<HTMLInputElement>("input[required]")
  const sync = (): void => {
    if (submit === null) return
    const phase = submit.dataset["phase"] ?? "idle"
    const inFlight = phase === "saving" || phase === "reviewing"
    submit.disabled = inFlight || Array.from(requiredFields).some((field) => field.value.trim().length === 0)
  }
  requiredFields.forEach((field) => field.addEventListener("input", sync))
  if (submit !== null) {
    new MutationObserver(sync).observe(submit, { attributes: true, attributeFilter: ["data-phase"] })
  }
  sync()
  return sync
}

type JournalKeyEvent = Pick<
  KeyboardEvent,
  "isTrusted" | "metaKey" | "ctrlKey" | "shiftKey" | "key" | "preventDefault"
>

export const handleJournalKeydown = (
  event: JournalKeyEvent,
  root: HTMLElement,
  workflow: Pick<CaptureWorkflow, "submit">,
): void => {
  if (!event.isTrusted) return
  if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "j") {
    openSheet(root)
  }
  const submit = root.querySelector<HTMLButtonElement>("[data-submit-review]")
  if (
    (event.metaKey || event.ctrlKey) &&
    event.key === "Enter" &&
    root.classList.contains("fj-sheet-open") &&
    submit?.disabled === false
  ) {
    event.preventDefault()
    void workflow.submit()
  }
}

type OverlayKeyGuardEvent = JournalKeyEvent & Pick<KeyboardEvent, "stopPropagation">

export const guardOverlayKeydown = (
  event: OverlayKeyGuardEvent,
  root: HTMLElement,
  workflow: Pick<CaptureWorkflow, "submit">,
): void => {
  handleJournalKeydown(event, root, workflow)
  event.stopPropagation()
}

export const bindJournalChrome = (
  root: HTMLElement,
  workflow: CaptureWorkflow,
  draft: DraftController,
): void => {
  root.querySelector<HTMLButtonElement>("[data-open-sheet]")?.addEventListener("click", (event) => {
    if (event.isTrusted) openSheet(root)
  })
  root.querySelector<HTMLButtonElement>("[data-close-sheet]")?.addEventListener("click", (event) => {
    if (event.isTrusted) void draft.flush().then(() => closeSheet(root))
  })
  bindUtilityActionButtons(root, workflow)
  // TradingView's document-level hotkeys steal digits (interval dialog) and
  // backspace from the overlay fields — keyboard events must not leave the overlay.
  root.addEventListener("keydown", (event) => guardOverlayKeydown(event, root, workflow))
  root.addEventListener("keypress", (event) => event.stopPropagation())
  root.addEventListener("keyup", (event) => event.stopPropagation())
  document.addEventListener("keydown", (event) => handleJournalKeydown(event, root, workflow))
  chrome.runtime.onMessage.addListener((message: unknown) => {
    if (typeof message !== "object" || message === null || !("kind" in message)) return
    if (message.kind === "open-sheet") {
      openSheet(root)
      return
    }
    if (
      message.kind === "screenshot-captured" &&
      "captureRequestId" in message &&
      typeof message.captureRequestId === "string"
    ) {
      workflow.acknowledgeScreenshot(message.captureRequestId)
    }
  })
}
