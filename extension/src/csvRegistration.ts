import type { CaptureWorkflow } from "./captureWorkflow"
import { getInputValue } from "./dom"
import type { BarSeriesCoverage } from "./messageProtocol"
import { getBarCoverage, registerBarSeries } from "./messages"
import { renderReview } from "./reviewRenderer"
import { getSettings } from "./storage"

const HORIZON_BARS = 40
const SESSION_MINUTES_PER_DAY = 391
const CALENDAR_DAYS_PER_TRADING_DAY = 1.5
const DAY_MS = 24 * 60 * 60 * 1000

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
      message: "CSV not registered — export chart data after this session",
      registerDisabled: false,
    }
  }
  const requiredEnd = requiredCoverageEnd(decisionTimeIso, minutes)
  const coverageEnd = new Date(coverage.last_time_exchange)
  if (requiredEnd !== null && !Number.isNaN(coverageEnd.getTime()) && coverageEnd >= requiredEnd) {
    return {
      state: "covered",
      message: `CSV registered ✓ export not needed (${coverage.bar_count} bars, through ${coverage.last_time_exchange.slice(0, 10)})`,
      registerDisabled: true,
    }
  }
  return {
    state: "needed",
    message: `CSV registered through ${coverage.last_time_exchange.slice(0, 10)} — export again to cover this judgment's scoring window`,
    registerDisabled: false,
  }
}

type CsvRegistrationController = {
  readonly refresh: () => Promise<void>
}

const applyBadge = (root: HTMLElement, badge: CsvBadge): void => {
  const status = root.querySelector<HTMLElement>("[data-csv-status]")
  if (status !== null) {
    status.textContent = badge.message
    status.dataset["csvState"] = badge.state
  }
  const button = root.querySelector<HTMLButtonElement>("[data-register-csv]")
  if (button !== null) {
    button.disabled = badge.registerDisabled
  }
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
  const button = root.querySelector<HTMLButtonElement>("[data-register-csv]")
  const fileInput = root.querySelector<HTMLInputElement>("[data-csv-file]")

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
    try {
      const response = await getBarCoverage(await getSettings(), symbol, timeframe)
      if (!response.ok) {
        applyBadge(root, {
          state: "unknown",
          message: `CSV coverage check failed: ${response.error}`,
          registerDisabled: false,
        })
        return
      }
      applyBadge(
        root,
        coverageBadge(timeframe, decisionTime, response.registered, response.coverage),
      )
    } catch {
      applyBadge(root, {
        state: "unknown",
        message: "CSV coverage check failed",
        registerDisabled: false,
      })
    }
  }

  const register = async (file: File): Promise<void> => {
    const { symbol, timeframe } = chartKeys(root)
    if (!symbol || !timeframe || status === null) {
      return
    }
    status.textContent = "Registering CSV and running deferred reviews…"
    status.dataset["csvState"] = "unknown"
    try {
      const csvText = await file.text()
      const response = await registerBarSeries(await getSettings(), symbol, timeframe, csvText)
      if (!response.ok) {
        status.textContent = `CSV registration failed: ${response.error}`
        return
      }
      status.textContent =
        `CSV registered (${response.coverage.bar_count} bars) · ` +
        `${response.reviews.length} review(s) completed`
      const currentId = workflow.lastCaptureId()
      const currentReview = response.reviews.find(
        (review) => review.capture_id === currentId,
      )
      if (currentReview !== undefined) {
        renderReview(root, currentReview)
      }
      await refresh()
    } catch (error) {
      status.textContent =
        error instanceof Error
          ? `CSV registration failed: ${error.message}`
          : "CSV registration failed"
    }
  }

  button?.addEventListener("click", (event) => {
    if (event.isTrusted) {
      fileInput?.click()
    }
  })
  fileInput?.addEventListener("change", () => {
    const file = fileInput.files?.[0]
    if (file !== undefined) {
      void register(file)
    }
    fileInput.value = ""
  })

  return { refresh }
}
