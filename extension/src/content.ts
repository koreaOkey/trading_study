import { createElement, getInputValue, setState } from "./dom"
import type { OverlayState } from "./dom"
import { createCaptureWorkflow } from "./captureWorkflow"
import type { CaptureWorkflow } from "./captureWorkflow"
import { currentExchangeIso, extractSymbolCandidate, extractTimeframeCandidate, today } from "./metadata"
import { restoreDraft, saveDraft } from "./storage"
import { bindUtilityActionButtons } from "./utilityActions"

const ROOT_ID = "fractal-replay-journal-root"

const initialState: OverlayState = {
  status: "checking",
  message: "Backend checking",
  warnings: ["provider_symbol_unconfirmed", "price_basis_unverified"],
}

const openSheet = (root: HTMLElement): void => {
  root.classList.add("fj-sheet-open")
}

const closeSheet = (root: HTMLElement): void => {
  root.classList.remove("fj-sheet-open")
}

const bindDecisionButtons = (root: HTMLElement, workflow: CaptureWorkflow): void => {
  root.querySelectorAll<HTMLButtonElement>("[data-decision]").forEach((button) => {
    button.addEventListener("click", () => {
      const decision = button.dataset["decision"]
      if (decision === "long" || decision === "short" || decision === "watch" || decision === "skip") {
        void workflow.capture(decision)
      }
    })
  })
}

const bindChrome = (root: HTMLElement, workflow: CaptureWorkflow): void => {
  root.querySelector<HTMLButtonElement>("[data-open-sheet]")?.addEventListener("click", () => {
    openSheet(root)
  })
  root.querySelector<HTMLButtonElement>("[data-close-sheet]")?.addEventListener("click", () => {
    void saveDraft(root).then(() => closeSheet(root))
  })
  bindUtilityActionButtons(root, workflow)
  root.querySelectorAll("input, textarea").forEach((field) => {
    field.addEventListener("change", () => void saveDraft(root))
  })
  document.addEventListener("keydown", (event) => {
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

const renderOverlay = (): HTMLElement => {
  const root = createElement("section", "fj-root")
  root.id = ROOT_ID
  root.innerHTML = `
    <div class="fj-dock">
      <div>
        <div class="fj-kicker">Fractal Replay</div>
        <strong>Capture dock</strong>
      </div>
      <span class="fj-status" data-status="checking">Backend checking</span>
      <button class="fj-primary" data-open-sheet>Capture decision</button>
      <span class="fj-hotkey">⌘/Ctrl + Shift + J</span>
    </div>
    <div class="fj-sheet">
      <header class="fj-header">
        <div>
          <div class="fj-kicker">Fractal Replay</div>
          <strong>Journal Capture</strong>
        </div>
        <button class="fj-icon" data-close-sheet>×</button>
      </header>
      <section class="fj-section">
        <div class="fj-section-title">Extracted candidate - read only</div>
        <div class="fj-readonly">${extractSymbolCandidate() || "unknown"} · ${extractTimeframeCandidate()} · low</div>
      </section>
      <section class="fj-section fj-confirmed">
        <div class="fj-section-title">Confirmed for scoring - editable</div>
        <div class="fj-grid">
          <label>Symbol<input data-field="symbol" value="${extractSymbolCandidate()}" /></label>
          <label>Provider<input data-field="providerSymbol" value="${extractSymbolCandidate()}" /></label>
          <label>TF<input data-field="timeframe" value="${extractTimeframeCandidate()}" /></label>
          <label>Date<input data-field="tradeDate" value="${today()}" /></label>
          <label class="fj-field-wide">Decision time<input data-field="decisionTime" value="${currentExchangeIso()}" /></label>
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
      <div class="fj-actions">
        <button data-decision="long">Long</button>
        <button data-decision="short">Short</button>
        <button data-decision="watch">Watch</button>
        <button data-decision="skip">Skip</button>
      </div>
    </div>
  `
  return root
}

const mount = async (): Promise<void> => {
  if (document.getElementById(ROOT_ID) !== null) {
    return
  }
  const root = renderOverlay()
  const workflow = createCaptureWorkflow(root, () => closeSheet(root))
  bindChrome(root, workflow)
  bindDecisionButtons(root, workflow)
  document.documentElement.append(root)
  setState(root, initialState)
  await restoreDraft(root)
  if (getInputValue(root, "symbol").length === 0) {
    openSheet(root)
  }
  await workflow.checkBackend()
}

void mount()
