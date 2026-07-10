import { createCaptureWorkflow } from "./captureWorkflow"
import { getInputValue, setState } from "./dom"
import type { OverlayState } from "./dom"
import { bindDraggableOverlay } from "./drag"
import {
  bindDraftAutosave,
  bindHypothesis,
  bindJournalChrome,
  bindSubmitValidity,
} from "./journalBindings"
import { fallbackCandidateMetadata } from "./metadata"
import type { CandidateMetadata } from "./metadata"
import { applyCandidate, openSheet, renderOverlay, ROOT_ID } from "./overlayView"
import { restoreDraft } from "./storage"
import { bindTradingViewBridge, requestFreshPageMetadata } from "./tradingViewBridge"

const initialState: OverlayState = {
  status: "checking",
  message: "Backend checking",
  warnings: ["provider_symbol_unconfirmed", "price_basis_unverified"],
}

const mount = async (): Promise<void> => {
  if (document.getElementById(ROOT_ID) !== null) return
  let candidate = fallbackCandidateMetadata()
  const { host, root } = renderOverlay()
  candidate = applyCandidate(root, candidate)
  const refreshCandidate = async (): Promise<CandidateMetadata | null> => {
    const refreshed = await requestFreshPageMetadata()
    if (refreshed !== null) candidate = applyCandidate(root, refreshed)
    return refreshed
  }
  const workflow = createCaptureWorkflow({ root, getCandidate: () => candidate, refreshCandidate })
  const draft = bindDraftAutosave(root)
  const syncHypothesis = bindHypothesis(root, draft)
  const syncSubmitValidity = bindSubmitValidity(root)
  bindJournalChrome(root, workflow, draft)
  document.documentElement.append(host)
  setState(root, initialState)
  await restoreDraft(root)
  syncHypothesis()
  candidate = applyCandidate(root, candidate)
  syncSubmitValidity()
  bindTradingViewBridge((nextCandidate) => {
    candidate = applyCandidate(root, nextCandidate)
    syncSubmitValidity()
  })
  await bindDraggableOverlay(root)
  if (getInputValue(root, "symbol").length === 0) openSheet(root)
  await workflow.checkBackend()
}

void mount()
