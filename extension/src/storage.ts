import { autoFieldDatasetKey, getInputValue, getTextareaValue } from "./dom"
import type { ExtensionSettings } from "./types"

const API_TOKEN_KEY = "apiToken"
const CONFIRMED_OVERRIDE_FIELDS = ["symbol", "providerSymbol", "timeframe", "decisionTime"] as const
type ConfirmedOverrideField = (typeof CONFIRMED_OVERRIDE_FIELDS)[number]
type ConfirmedOverrides = Partial<Record<ConfirmedOverrideField, string>>

export const manualOverrideValue = (
  value: string,
  automaticValue: string | undefined,
): string | undefined =>
  automaticValue === undefined
    ? value || undefined
    : value !== automaticValue
      ? value
      : undefined

export const parseConfirmedOverrides = (draft: unknown): ConfirmedOverrides => {
  if (
    typeof draft !== "object" ||
    draft === null ||
    !("confirmedOverrides" in draft) ||
    typeof draft.confirmedOverrides !== "object" ||
    draft.confirmedOverrides === null
  ) {
    return {}
  }
  const overrides: ConfirmedOverrides = {}
  for (const field of CONFIRMED_OVERRIDE_FIELDS) {
    const value = Reflect.get(draft.confirmedOverrides, field)
    if (typeof value === "string") {
      overrides[field] = value
    }
  }
  return overrides
}

export const DEFAULT_SETTINGS: ExtensionSettings = {
  apiBaseUrl: "http://127.0.0.1:8766",
  apiToken: "",
}

export const loadApiToken = async (): Promise<string> => {
  const [synced, local] = await Promise.all([
    chrome.storage.sync.get([API_TOKEN_KEY]),
    chrome.storage.local.get([API_TOKEN_KEY]),
  ])
  const localToken = local[API_TOKEN_KEY]
  const syncedToken = synced[API_TOKEN_KEY]
  if (syncedToken !== undefined) {
    await chrome.storage.sync.remove(API_TOKEN_KEY)
  }
  if (typeof localToken === "string") {
    return localToken
  }
  if (typeof syncedToken === "string" && syncedToken.length > 0) {
    await chrome.storage.local.set({ [API_TOKEN_KEY]: syncedToken })
    return syncedToken
  }
  return DEFAULT_SETTINGS.apiToken
}

export const saveApiToken = async (apiToken: string): Promise<void> => {
  await Promise.all([
    chrome.storage.local.set({ [API_TOKEN_KEY]: apiToken }),
    chrome.storage.sync.remove(API_TOKEN_KEY),
  ])
}

export const getSettings = async (): Promise<ExtensionSettings> => {
  const [synced, apiToken] = await Promise.all([
    chrome.storage.sync.get(["apiBaseUrl"]),
    loadApiToken(),
  ])
  return {
    apiBaseUrl:
      typeof synced["apiBaseUrl"] === "string" && synced["apiBaseUrl"].length > 0
        ? synced["apiBaseUrl"]
        : DEFAULT_SETTINGS.apiBaseUrl,
    apiToken,
  }
}

export const saveDraft = async (root: HTMLElement): Promise<void> => {
  const confirmedOverrides: ConfirmedOverrides = {}
  for (const field of CONFIRMED_OVERRIDE_FIELDS) {
    const value = getInputValue(root, field)
    const automaticValue = root.dataset[autoFieldDatasetKey(field)]
    const override = manualOverrideValue(value, automaticValue)
    if (override !== undefined) {
      confirmedOverrides[field] = override
    }
  }
  const draft = {
    confirmedOverrides,
    marketDivCode: getInputValue(root, "marketDivCode"),
    exchangeTz: getInputValue(root, "exchangeTz"),
    priceBasis: getInputValue(root, "priceBasis"),
    sessionState: getInputValue(root, "sessionState"),
    invalidation: getInputValue(root, "invalidation"),
    notes: getTextareaValue(root, "notes"),
  } as const
  await chrome.storage.local.set({ fractalReplayDraft: draft })
}

export const restoreDraft = async (root: HTMLElement): Promise<void> => {
  const stored = await chrome.storage.local.get(["fractalReplayDraft"])
  const draft = stored["fractalReplayDraft"]
  if (typeof draft !== "object" || draft === null) {
    return
  }
  const confirmedOverrides = parseConfirmedOverrides(draft)
  for (const field of CONFIRMED_OVERRIDE_FIELDS) {
    const input = root.querySelector<HTMLInputElement>(`[data-field="${field}"]`)
    const value = confirmedOverrides[field]
    if (input !== null && value !== undefined) {
      input.value = value
    }
  }
  for (const field of [
    "marketDivCode",
    "exchangeTz",
    "priceBasis",
    "sessionState",
    "invalidation",
  ] as const) {
    const input = root.querySelector<HTMLInputElement>(`[data-field="${field}"]`)
    const value = field in draft ? draft[field] : undefined
    if (input !== null && typeof value === "string") {
      input.value = value
    }
  }
  const notes = root.querySelector<HTMLTextAreaElement>('[data-field="notes"]')
  const notesValue = "notes" in draft ? draft.notes : undefined
  if (notes !== null && typeof notesValue === "string") {
    notes.value = notesValue
  }
}
