import { autoFieldDatasetKey, createElement, getInputValue, setState } from "./dom"
import type { OverlayState } from "./dom"
import { bindDraggableOverlay, reclampOverlay } from "./drag"
import { createCaptureWorkflow } from "./captureWorkflow"
import type { CaptureWorkflow } from "./captureWorkflow"
import {
  currentExchangeIso,
  fallbackCandidateMetadata,
} from "./metadata"
import type { CandidateMetadata } from "./metadata"
import { restoreDraft, saveDraft } from "./storage"
import {
  bindTradingViewBridge,
  requestFreshPageMetadata,
  requestPageMetadata,
} from "./tradingViewBridge"
import { bindUtilityActionButtons } from "./utilityActions"
import actionsCss from "./actions.css"
import overlayCss from "./styles.css"

const ROOT_ID = "fractal-replay-journal-root"

const initialState: OverlayState = {
  status: "checking",
  message: "Backend checking",
  warnings: ["provider_symbol_unconfirmed", "price_basis_unverified"],
}

const openSheet = (root: HTMLElement): void => {
  root.classList.add("fj-sheet-open")
  requestPageMetadata()
  window.requestAnimationFrame(() => reclampOverlay(root))
}

const closeSheet = (root: HTMLElement): void => {
  root.classList.remove("fj-sheet-open")
  window.requestAnimationFrame(() => reclampOverlay(root))
}

const bindDecisionButtons = (root: HTMLElement, workflow: CaptureWorkflow): void => {
  root.querySelectorAll<HTMLButtonElement>("[data-decision]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (!event.isTrusted) {
        return
      }
      const decision = button.dataset["decision"]
      if (decision === "long" || decision === "short" || decision === "watch" || decision === "skip") {
        void workflow.capture(decision)
      }
    })
  })
}

const bindChrome = (root: HTMLElement, workflow: CaptureWorkflow): void => {
  root.querySelector<HTMLButtonElement>("[data-open-sheet]")?.addEventListener("click", (event) => {
    if (!event.isTrusted) {
      return
    }
    openSheet(root)
  })
  root.querySelector<HTMLButtonElement>("[data-close-sheet]")?.addEventListener("click", (event) => {
    if (!event.isTrusted) {
      return
    }
    void saveDraft(root).then(() => closeSheet(root))
  })
  bindUtilityActionButtons(root, workflow)
  root.querySelectorAll("input, textarea").forEach((field) => {
    field.addEventListener("change", (event) => {
      if (event.isTrusted) {
        void saveDraft(root)
      }
    })
  })
  document.addEventListener("keydown", (event) => {
    if (!event.isTrusted) {
      return
    }
    if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "j") {
      openSheet(root)
    }
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && root.classList.contains("fj-sheet-open")) {
      void workflow.capture("watch")
    }
  })
  chrome.runtime.onMessage.addListener((message: unknown) => {
    if (
      typeof message === "object" &&
      message !== null &&
      "kind" in message &&
      message.kind === "open-sheet"
    ) {
      openSheet(root)
    }
  })
}

type RenderedOverlay = {
  readonly host: HTMLElement
  readonly root: HTMLElement
}

const renderOverlay = (candidate: CandidateMetadata): RenderedOverlay => {
  const host = createElement("div", "")
  host.id = ROOT_ID
  const shadow = host.attachShadow({ mode: "closed" })
  const style = document.createElement("style")
  style.textContent = `${overlayCss}\n${actionsCss}`
  const root = createElement("section", "fj-root")
  root.innerHTML = `
    <div class="fj-dock" data-drag-handle>
      <div>
        <div class="fj-kicker">Fractal Replay</div>
        <strong>Capture dock</strong>
      </div>
      <span class="fj-status" data-status="checking">Backend checking</span>
      <button class="fj-primary" data-open-sheet>Capture decision</button>
      <span class="fj-hotkey">⌘/Ctrl + Shift + J</span>
    </div>
    <div class="fj-sheet">
      <header class="fj-header" data-drag-handle>
        <div>
          <div class="fj-kicker">Fractal Replay</div>
          <strong>Journal Capture</strong>
        </div>
        <button class="fj-icon" data-close-sheet aria-label="Close">×</button>
      </header>
      <div class="fj-sheet-scroll">
      <section class="fj-section">
        <div class="fj-section-title">Extracted candidate - read only</div>
        <div class="fj-readonly" data-extracted-candidate></div>
      </section>
      <section class="fj-section fj-confirmed">
        <div class="fj-section-title">Confirmed for scoring - editable</div>
        <div class="fj-grid">
          <label>Symbol<input data-field="symbol" value="${candidate.symbol}" /></label>
          <label>Provider<input data-field="providerSymbol" value="${candidate.symbol}" /></label>
          <label>TF<input data-field="timeframe" value="${candidate.timeframe}" /></label>
          <label class="fj-field-wide">Decision time<input data-field="decisionTime" value="${candidate.decisionTime}" /></label>
          <label>TZ<input data-field="exchangeTz" value="Asia/Seoul" /></label>
          <label class="fj-field-wide">Basis<input data-field="priceBasis" value="unknown_unadjusted_assumed" /></label>
          <label>Session<input data-field="sessionState" value="regular" /></label>
          <label>Market<input data-field="marketDivCode" value="J" /></label>
          <label>Invalidation<input data-field="invalidation" value="" /></label>
        </div>
      </section>
      <textarea data-field="notes" placeholder="Decision context"></textarea>
      <div class="fj-warnings" data-warnings></div>
      <div class="fj-utility-actions">
        <button data-save-draft>Save draft</button>
        <button data-retry-capture>Retry</button>
        <button data-copy-payload>Copy payload</button>
      </div>
      </div>
      <div class="fj-actions">
        <button data-decision="long">Long</button>
        <button data-decision="short">Short</button>
        <button data-decision="watch">Watch</button>
        <button data-decision="skip">Skip</button>
      </div>
    </div>
  `
  shadow.append(style, root)
  return { host, root }
}

const setAutoField = (root: HTMLElement, field: string, value: string): void => {
  if (value.length === 0) {
    return
  }
  const input = root.querySelector<HTMLInputElement>(`[data-field="${field}"]`)
  if (input === null) {
    return
  }
  const key = autoFieldDatasetKey(field)
  const previousAuto = root.dataset[key] ?? input.value
  if (input.value.length === 0 || input.value === previousAuto) {
    input.value = value
  }
  root.dataset[key] = value
}

const applyCandidate = (root: HTMLElement, candidate: CandidateMetadata): CandidateMetadata => {
  const decisionTime = candidate.decisionTime || getInputValue(root, "decisionTime") || currentExchangeIso()
  const normalized = { ...candidate, decisionTime }
  setAutoField(root, "symbol", normalized.symbol)
  setAutoField(root, "providerSymbol", normalized.symbol)
  setAutoField(root, "timeframe", normalized.timeframe)
  setAutoField(root, "decisionTime", normalized.decisionTime)
  const summary = root.querySelector<HTMLElement>("[data-extracted-candidate]")
  if (summary !== null) {
    const segments = [
      normalized.symbol || "unknown",
      normalized.timeframe || "unknown TF",
      normalized.replayActive ? `replay ${normalized.decisionTime}` : "live",
    ]
    summary.replaceChildren(
      ...segments.map((segment) => createElement("span", "fj-candidate-segment", segment)),
    )
  }
  return normalized
}

const mount = async (): Promise<void> => {
  if (document.getElementById(ROOT_ID) !== null) {
    return
  }
  let candidate = fallbackCandidateMetadata()
  const { host, root } = renderOverlay(candidate)
  candidate = applyCandidate(root, candidate)
  const refreshCandidate = async (): Promise<CandidateMetadata | null> => {
    const refreshed = await requestFreshPageMetadata()
    if (refreshed !== null) {
      candidate = applyCandidate(root, refreshed)
    }
    return refreshed
  }
  const workflow = createCaptureWorkflow(
    root,
    () => closeSheet(root),
    () => candidate,
    refreshCandidate,
  )
  bindChrome(root, workflow)
  bindDecisionButtons(root, workflow)
  document.documentElement.append(host)
  setState(root, initialState)
  await restoreDraft(root)
  candidate = applyCandidate(root, candidate)
  bindTradingViewBridge((nextCandidate) => {
    candidate = applyCandidate(root, nextCandidate)
  })
  await bindDraggableOverlay(root)
  if (getInputValue(root, "symbol").length === 0) {
    openSheet(root)
  }
  await workflow.checkBackend()
}

void mount()
