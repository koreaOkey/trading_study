import type { CaptureWorkflow } from "./captureWorkflow"
import { getInputValue } from "./dom"
import type { BarSeriesCoverage } from "./messageProtocol"
import { getBarCoverage, registerBarSeries } from "./messages"
import { renderReview } from "./reviewRenderer"
import { getSettings } from "./storage"
import { requestFreshPageMetadata, requestPageBars } from "./tradingViewBridge"
import type { PageBars } from "./tradingViewBridge"

const HORIZON_BARS = 40
const SESSION_MINUTES_PER_DAY = 391
const CALENDAR_DAYS_PER_TRADING_DAY = 1.5
const DAY_MS = 24 * 60 * 60 * 1000
const COVERAGE_CACHE_MS = 60_000

export type CsvBadge = {
  readonly state: "not-needed" | "covered" | "needed" | "unknown"
  readonly message: string
  readonly registerDisabled: boolean
  // Extraction now pulls the full exchange history and registration merges,
  // so re-extracting is useful (backtesting, appending fresh bars) even when
  // the scoring window is already covered. Only daily charts opt out — those
  // are served by KIS directly.
  readonly extractDisabled: boolean
}

export const parseTimeframeMinutes = (timeframe: string): number | null => {
  if (!/^\d+$/.test(timeframe)) {
    return null
  }
  const minutes = Number.parseInt(timeframe, 10)
  return minutes > 0 ? minutes : null
}

export const requiredCoverageEnd = (
  decisionTimeIso: string,
  timeframeMinutes: number,
): Date | null => {
  const decision = new Date(decisionTimeIso)
  if (Number.isNaN(decision.getTime())) {
    return null
  }
  // Scoring needs HORIZON_BARS completed bars after the decision. Convert to
  // calendar days via KRX session length; the x1.5 pad absorbs weekends and
  // holidays so "covered" is never claimed while scoring bars are missing.
  const barsPerDay = Math.max(1, Math.ceil(SESSION_MINUTES_PER_DAY / timeframeMinutes))
  const tradingDays = Math.ceil(HORIZON_BARS / barsPerDay)
  const calendarDays = Math.ceil(tradingDays * CALENDAR_DAYS_PER_TRADING_DAY)
  return new Date(decision.getTime() + calendarDays * DAY_MS)
}

export const coverageBadge = (
  timeframe: string,
  decisionTimeIso: string,
  registered: boolean,
  coverage: BarSeriesCoverage | null,
  now: Date = new Date(),
): CsvBadge => {
  const minutes = parseTimeframeMinutes(timeframe)
  if (minutes === null) {
    return {
      state: "not-needed",
      message: "CSV 불필요 — 일봉은 KIS로 자동 처리",
      registerDisabled: true,
      extractDisabled: true,
    }
  }
  if (!registered || coverage === null) {
    return {
      state: "needed",
      message: "봉 미등록 — 리플레이 전에 전체 차트를 추출해두세요",
      registerDisabled: false,
      extractDisabled: false,
    }
  }
  const requiredEnd = requiredCoverageEnd(decisionTimeIso, minutes)
  const coverageEnd = new Date(coverage.last_time_exchange)
  if (requiredEnd !== null && !Number.isNaN(coverageEnd.getTime()) && coverageEnd >= requiredEnd) {
    return {
      state: "covered",
      message: `봉 등록됨 ✓ 채점 구간 커버 (${coverage.bar_count}봉, ${coverage.last_time_exchange.slice(0, 10)}까지)`,
      registerDisabled: true,
      extractDisabled: false,
    }
  }
  // A live-chart decision puts requiredEnd in the future, where bars cannot
  // exist yet — extraction can only ever reach the newest completed bar. If
  // coverage is already that fresh, a re-extract adds nothing; scoring
  // catches up as bars complete. The allowance spans the worst regular gap:
  // Friday's last 4h bar to Monday's first completed one is three days.
  const freshnessAllowanceMs = 3 * DAY_MS + 2 * minutes * 60_000
  if (
    requiredEnd !== null &&
    !Number.isNaN(coverageEnd.getTime()) &&
    requiredEnd > now &&
    now.getTime() - coverageEnd.getTime() <= freshnessAllowanceMs
  ) {
    return {
      state: "covered",
      message: `봉 최신까지 등록됨 ✓ (${coverage.bar_count}봉) — 채점은 새 봉이 쌓이는 대로`,
      registerDisabled: true,
      extractDisabled: false,
    }
  }
  return {
    state: "needed",
    message: `봉이 ${coverage.last_time_exchange.slice(0, 10)}까지만 등록됨 — 다시 추출하세요`,
    registerDisabled: false,
    extractDisabled: false,
  }
}

export const buildCsvText = (
  columns: readonly string[],
  rows: ReadonlyArray<ReadonlyArray<number | null>>,
): string => {
  const lines = [
    columns.join(","),
    ...rows.map((row) => row.map((value) => (value === null ? "" : String(value))).join(",")),
  ]
  return `${lines.join("\n")}\n`
}

type CsvRegistrationController = {
  readonly refresh: () => Promise<void>
  readonly isEvidenceReady: () => boolean
}

type CoverageCache = {
  readonly key: string
  readonly at: number
  readonly registered: boolean
  readonly coverage: BarSeriesCoverage | null
}

const applyBadge = (root: HTMLElement, badge: CsvBadge): void => {
  const status = root.querySelector<HTMLElement>("[data-csv-status]")
  if (status !== null) {
    status.textContent = badge.message
    status.dataset["csvState"] = badge.state
  }
  root.querySelectorAll<HTMLButtonElement>("[data-register-csv]").forEach((button) => {
    button.disabled = badge.registerDisabled
  })
  root.querySelectorAll<HTMLButtonElement>("[data-extract-csv]").forEach((button) => {
    button.disabled = badge.extractDisabled
  })
}

const chartKeys = (root: HTMLElement): { symbol: string; timeframe: string } => ({
  symbol: getInputValue(root, "providerSymbol") || getInputValue(root, "symbol"),
  timeframe: getInputValue(root, "timeframe"),
})

export const bindCsvRegistration = (
  root: HTMLElement,
  workflow: Pick<CaptureWorkflow, "lastCaptureId">,
): CsvRegistrationController => {
  const status = root.querySelector<HTMLElement>("[data-csv-status]")
  const extractButton = root.querySelector<HTMLButtonElement>("[data-extract-csv]")
  const fileButton = root.querySelector<HTMLButtonElement>("[data-register-csv]")
  const fileInput = root.querySelector<HTMLInputElement>("[data-csv-file]")
  let coverageCache: CoverageCache | null = null
  let lastBadgeState: CsvBadge["state"] = "unknown"
  // The 750ms metadata poll re-renders the badge; operation statuses (extract
  // progress, registration results, errors) must hold the line long enough to
  // be read instead of being clobbered by the next poll tick.
  let statusHeldUntil = 0

  const showBadge = (badge: CsvBadge): void => {
    if (Date.now() < statusHeldUntil) {
      return
    }
    lastBadgeState = badge.state
    applyBadge(root, badge)
  }

  const setStatus = (
    message: string,
    state: CsvBadge["state"] = "unknown",
    holdMs = 20_000,
  ): void => {
    statusHeldUntil = Date.now() + holdMs
    if (status !== null) {
      status.textContent = message
      status.dataset["csvState"] = state
    }
  }

  const refresh = async (): Promise<void> => {
    const { symbol, timeframe } = chartKeys(root)
    const decisionTime = getInputValue(root, "decisionTime")
    if (!symbol || !timeframe) {
      return
    }
    if (parseTimeframeMinutes(timeframe) === null) {
      showBadge(coverageBadge(timeframe, decisionTime, false, null))
      return
    }
    const key = `${symbol}|${timeframe}`
    if (coverageCache !== null && coverageCache.key === key) {
      // The replay cursor updates decisionTime every tick; recompute the badge
      // locally and only re-ask the backend once the cache expires.
      showBadge(
        coverageBadge(timeframe, decisionTime, coverageCache.registered, coverageCache.coverage),
      )
      if (Date.now() - coverageCache.at < COVERAGE_CACHE_MS) {
        return
      }
    }
    try {
      const response = await getBarCoverage(await getSettings(), symbol, timeframe)
      if (!response.ok) {
        setStatus(`CSV 상태 확인 실패: ${response.error}`, "unknown", 0)
        return
      }
      coverageCache = {
        key,
        at: Date.now(),
        registered: response.registered,
        coverage: response.coverage,
      }
      showBadge(
        coverageBadge(timeframe, decisionTime, response.registered, response.coverage),
      )
    } catch {
      setStatus("CSV 상태 확인 실패", "unknown", 0)
    }
  }

  const registerText = async (csvText: string): Promise<void> => {
    const { symbol, timeframe } = chartKeys(root)
    if (!symbol || !timeframe) {
      return
    }
    setStatus("봉 등록 및 대기 리뷰 실행 중…")
    try {
      const response = await registerBarSeries(await getSettings(), symbol, timeframe, csvText)
      if (!response.ok) {
        setStatus(`등록 실패: ${response.error}`)
        return
      }
      setStatus(
        `${response.coverage.bar_count}봉 등록됨 · 리뷰 ${response.reviews.length}건 완료`,
        "covered",
      )
      const currentId = workflow.lastCaptureId()
      const currentReview = response.reviews.find(
        (review) => review.capture_id === currentId,
      )
      if (currentReview !== undefined) {
        renderReview(root, currentReview)
      }
      coverageCache = null
      await refresh()
    } catch (error) {
      setStatus(
        error instanceof Error ? `등록 실패: ${error.message}` : "등록 실패",
      )
    }
  }

  const extract = async (): Promise<void> => {
    setStatus("전체 기간 로드 시작…")
    // A replay-mode series stops at the cursor, so the scoring window after
    // the decision would be missing from the extract.
    const candidate = await requestFreshPageMetadata()
    if (candidate?.replayActive === true) {
      setStatus("리플레이를 먼저 종료하세요 — 판단 이후 봉이 포함돼야 합니다", "needed")
      return
    }
    const bars: PageBars | null = await requestPageBars({
      fullHistory: true,
      onProgress: (loadedBars) => {
        setStatus(`과거 봉 로드 중… ${loadedBars.toLocaleString("ko-KR")}봉`, "unknown", 90_000)
      },
    })
    if (bars === null || bars.error !== null || bars.rows.length === 0) {
      setStatus(
        `차트 추출 실패 (${bars?.error ?? "응답 없음"}) — "CSV 파일 등록"을 사용하세요`,
      )
      return
    }
    await registerText(buildCsvText(bars.columns, bars.rows))
  }

  extractButton?.addEventListener("click", (event) => {
    if (event.isTrusted) {
      void extract()
    }
  })
  fileButton?.addEventListener("click", (event) => {
    if (event.isTrusted) {
      fileInput?.click()
    }
  })
  fileInput?.addEventListener("change", () => {
    const file = fileInput.files?.[0]
    if (file !== undefined) {
      void file.text().then(registerText)
    }
    fileInput.value = ""
  })

  return {
    refresh,
    isEvidenceReady: () => lastBadgeState === "covered" || lastBadgeState === "not-needed",
  }
}
