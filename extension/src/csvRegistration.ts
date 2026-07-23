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
): CsvBadge => {
  const minutes = parseTimeframeMinutes(timeframe)
  if (minutes === null) {
    return {
      state: "not-needed",
      message: "CSV not needed — daily scoring uses KIS directly",
      registerDisabled: true,
    }
  }
  if (!registered || coverage === null) {
    return {
      state: "needed",
      message: "CSV not registered — extract chart data after this session",
      registerDisabled: false,
    }
  }
  const requiredEnd = requiredCoverageEnd(decisionTimeIso, minutes)
  const coverageEnd = new Date(coverage.last_time_exchange)
  if (requiredEnd !== null && !Number.isNaN(coverageEnd.getTime()) && coverageEnd >= requiredEnd) {
    return {
      state: "covered",
      message: `CSV registered ✓ extract not needed (${coverage.bar_count} bars, through ${coverage.last_time_exchange.slice(0, 10)})`,
      registerDisabled: true,
    }
  }
  return {
    state: "needed",
    message: `CSV registered through ${coverage.last_time_exchange.slice(0, 10)} — extract again to cover this judgment's scoring window`,
    registerDisabled: false,
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
  root
    .querySelectorAll<HTMLButtonElement>("[data-extract-csv], [data-register-csv]")
    .forEach((button) => {
      button.disabled = badge.registerDisabled
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

  const setStatus = (message: string, state: CsvBadge["state"] = "unknown"): void => {
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
      applyBadge(root, coverageBadge(timeframe, decisionTime, false, null))
      return
    }
    const key = `${symbol}|${timeframe}`
    if (coverageCache !== null && coverageCache.key === key) {
      // The replay cursor updates decisionTime every tick; recompute the badge
      // locally and only re-ask the backend once the cache expires.
      applyBadge(
        root,
        coverageBadge(timeframe, decisionTime, coverageCache.registered, coverageCache.coverage),
      )
      if (Date.now() - coverageCache.at < COVERAGE_CACHE_MS) {
        return
      }
    }
    try {
      const response = await getBarCoverage(await getSettings(), symbol, timeframe)
      if (!response.ok) {
        setStatus(`CSV coverage check failed: ${response.error}`)
        return
      }
      coverageCache = {
        key,
        at: Date.now(),
        registered: response.registered,
        coverage: response.coverage,
      }
      applyBadge(
        root,
        coverageBadge(timeframe, decisionTime, response.registered, response.coverage),
      )
    } catch {
      setStatus("CSV coverage check failed")
    }
  }

  const registerText = async (csvText: string): Promise<void> => {
    const { symbol, timeframe } = chartKeys(root)
    if (!symbol || !timeframe) {
      return
    }
    setStatus("Registering bars and running deferred reviews…")
    try {
      const response = await registerBarSeries(await getSettings(), symbol, timeframe, csvText)
      if (!response.ok) {
        setStatus(`Registration failed: ${response.error}`)
        return
      }
      setStatus(
        `Registered ${response.coverage.bar_count} bars · ` +
          `${response.reviews.length} review(s) completed`,
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
        error instanceof Error
          ? `Registration failed: ${error.message}`
          : "Registration failed",
      )
    }
  }

  const extract = async (): Promise<void> => {
    setStatus("Reading chart data…")
    // A replay-mode series stops at the cursor, so the scoring window after
    // the decision would be missing from the extract.
    const candidate = await requestFreshPageMetadata()
    if (candidate?.replayActive === true) {
      setStatus("Exit replay first — the extract must include post-decision bars", "needed")
      return
    }
    const bars: PageBars | null = await requestPageBars()
    if (bars === null || bars.error !== null || bars.rows.length === 0) {
      setStatus(
        `Chart extract unavailable (${bars?.error ?? "timeout"}) — use "Register CSV file" instead`,
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

  return { refresh }
}
