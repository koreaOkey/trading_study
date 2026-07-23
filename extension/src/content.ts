import { createCaptureWorkflow } from "./captureWorkflow"
import { bindCsvRegistration } from "./csvRegistration"
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
import { bindReviewHistory } from "./reviewHistory"
import { restoreDraft } from "./storage"
import { bindTradingViewBridge, requestFreshPageMetadata } from "./tradingViewBridge"

const initialState: OverlayState = {
  status: "checking",
  message: "백엔드 확인 중",
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
  let csvRegistration: ReturnType<typeof bindCsvRegistration> | null = null
  const workflow = createCaptureWorkflow({
    root,
    getCandidate: () => candidate,
    refreshCandidate,
    reviewImmediately: () => csvRegistration?.isEvidenceReady() ?? false,
  })
  const draft = bindDraftAutosave(root)
  const syncHypothesis = bindHypothesis(root, draft)
  const syncSubmitValidity = bindSubmitValidity(root)
  bindJournalChrome(root, workflow, draft)
  csvRegistration = bindCsvRegistration(root, workflow)
  bindReviewHistory(root)
  document.documentElement.append(host)
  setState(root, initialState)
  await restoreDraft(root)
  syncHypothesis()
  candidate = applyCandidate(root, candidate)
  syncSubmitValidity()
  void csvRegistration?.refresh()
  bindTradingViewBridge((nextCandidate) => {
    candidate = applyCandidate(root, nextCandidate)
    syncSubmitValidity()
    void csvRegistration?.refresh()
  })
  await bindDraggableOverlay(root)
  if (getInputValue(root, "symbol").length === 0) openSheet(root)
  await workflow.checkBackend()
}

void mount()
