import { autoFieldDatasetKey, createElement, getInputValue } from "./dom"
import { reclampOverlay } from "./drag"
import { currentExchangeIso } from "./metadata"
import type { CandidateMetadata } from "./metadata"
import { requestPageMetadata } from "./tradingViewBridge"
import actionsCss from "./actions.css"
import overlayCss from "./styles.css"

export const ROOT_ID = "fractal-replay-journal-root"

export const openSheet = (root: HTMLElement): void => {
  root.classList.add("fj-sheet-open")
  requestPageMetadata()
  window.requestAnimationFrame(() => reclampOverlay(root))
}

export const closeSheet = (root: HTMLElement): void => {
  root.classList.remove("fj-sheet-open")
  window.requestAnimationFrame(() => reclampOverlay(root))
}

const overlayMarkup = (): string => `
  <div class="fj-dock" data-drag-handle>
    <div><div class="fj-kicker">Fractal Replay</div><strong>판단 저널</strong></div>
    <span class="fj-status" data-status="checking" role="status" aria-live="polite">백엔드 확인 중</span>
    <button class="fj-primary" type="button" data-open-sheet>저널 열기</button>
    <span class="fj-hotkey">Ctrl/Cmd + Shift + J</span>
  </div>
  <div class="fj-sheet">
    <header class="fj-header" data-drag-handle>
      <div><div class="fj-kicker">Fractal Replay</div><strong>판단 기록</strong></div>
      <button class="fj-icon" type="button" data-close-sheet aria-label="Close">×</button>
    </header>
    <div class="fj-sheet-scroll">
      <section class="fj-section">
        <div class="fj-section-title">자동 추출 값 · 읽기 전용</div>
        <div class="fj-readonly" data-extracted-candidate></div>
      </section>
      <section class="fj-section fj-confirmed">
        <div class="fj-section-title">확정 정보 · 수정 가능</div>
        <div class="fj-grid">
          <label>종목코드<input data-field="symbol" required autocomplete="off" /></label>
          <label>KIS 종목코드<input data-field="providerSymbol" required autocomplete="off" /></label>
          <label>타임프레임<input data-field="timeframe" required autocomplete="off" /></label>
          <label class="fj-field-wide">판단 시각<input data-field="decisionTime" required autocomplete="off" /></label>
        </div>
      </section>
      <input type="hidden" data-field="exchangeTz" value="Asia/Seoul" />
      <input type="hidden" data-field="priceBasis" value="unknown_unadjusted_assumed" />
      <input type="hidden" data-field="sessionState" value="regular" />
      <input type="hidden" data-field="marketDivCode" value="J" />
      <input type="hidden" data-field="hypothesis" value="uncertain" />
      <section class="fj-decision-context" aria-labelledby="fj-setup-title">
        <div class="fj-context-row">
          <div><div class="fj-section-title" id="fj-setup-title">셋업</div><strong>이평선 크로스</strong></div>
          <span class="fj-indicators">SMA 50 · SMA 200 · VWMA 100</span>
        </div>
        <div class="fj-field-label" id="fj-hypothesis-label">예상 시나리오</div>
        <div class="fj-segments" role="group" aria-labelledby="fj-hypothesis-label">
          <button type="button" data-hypothesis="golden_cross_expected" aria-pressed="false">골든크로스</button>
          <button type="button" data-hypothesis="dead_cross_expected" aria-pressed="false">데드크로스</button>
          <button type="button" data-hypothesis="uncertain" aria-pressed="true">미확정</button>
        </div>
        <label class="fj-note-label">판단 노트
          <textarea data-field="decisionNote" maxlength="2000" placeholder="판단 근거, 부족한 증거, 무효화 조건을 기록하세요."></textarea>
        </label>
        <div class="fj-draft-status" data-draft-status data-draft-state="ready" role="status" aria-live="polite">자동 저장 켜짐</div>
      </section>
      <section class="fj-csv-section">
        <div class="fj-csv-status" data-csv-status data-csv-state="unknown" role="status" aria-live="polite">CSV 상태 확인 중…</div>
        <button class="fj-register-csv" type="button" data-extract-csv>차트 추출·등록</button>
        <button class="fj-register-csv fj-register-csv-secondary" type="button" data-register-csv>CSV 파일 등록…</button>
        <input type="file" accept=".csv,text/csv" data-csv-file hidden />
      </section>
      <div class="fj-warnings" data-warnings aria-live="polite"></div>
      <section class="fj-review-section" data-review-section aria-live="polite" hidden>
        <div data-review></div>
        <button class="fj-retry-review" type="button" data-retry-review hidden>리뷰 재시도</button>
      </section>
      <section class="fj-history-section">
        <div class="fj-history-header">
          <span class="fj-section-title">최근 리뷰</span>
          <button class="fj-history-load" type="button" data-load-history>불러오기</button>
        </div>
        <div class="fj-history-list" data-history-list></div>
      </section>
    </div>
    <div class="fj-actions">
      <button class="fj-submit" type="button" data-submit-review data-phase="idle">리뷰 제출</button>
    </div>
  </div>`

export type RenderedOverlay = { readonly host: HTMLElement; readonly root: HTMLElement }

export const renderOverlay = (): RenderedOverlay => {
  const host = createElement("div", "")
  host.id = ROOT_ID
  const shadow = host.attachShadow({ mode: "closed" })
  const style = document.createElement("style")
  style.textContent = `${overlayCss}\n${actionsCss}`
  const root = createElement("section", "fj-root")
  root.setAttribute("aria-label", "Fractal replay decision journal")
  root.innerHTML = overlayMarkup()
  shadow.append(style, root)
  return { host, root }
}

const setAutoField = (root: HTMLElement, field: string, value: string): void => {
  if (value.length === 0) return
  const input = root.querySelector<HTMLInputElement>(`[data-field="${field}"]`)
  if (input === null) return
  const key = autoFieldDatasetKey(field)
  const previousAuto = root.dataset[key] ?? input.value
  if (input.value.length === 0 || input.value === previousAuto) input.value = value
  root.dataset[key] = value
}

export const applyCandidate = (
  root: HTMLElement,
  candidate: CandidateMetadata,
): CandidateMetadata => {
  const decisionTime = candidate.decisionTime || getInputValue(root, "decisionTime") || currentExchangeIso()
  const normalized = { ...candidate, decisionTime }
  setAutoField(root, "symbol", normalized.symbol)
  setAutoField(root, "providerSymbol", normalized.symbol)
  setAutoField(root, "timeframe", normalized.timeframe)
  setAutoField(root, "decisionTime", normalized.decisionTime)
  const summary = root.querySelector<HTMLElement>("[data-extracted-candidate]")
  if (summary !== null) {
    const segments = [
      normalized.symbol || "unknown symbol",
      normalized.timeframe || "unknown TF",
      normalized.replayActive ? `replay ${normalized.decisionTime}` : "live",
    ]
    summary.replaceChildren(
      ...segments.map((segment) => createElement("span", "fj-candidate-segment", segment)),
    )
  }
  return normalized
}
