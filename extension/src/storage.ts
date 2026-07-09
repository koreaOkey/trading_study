import { getInputValue, getTextareaValue } from "./dom"
import type { ExtensionSettings } from "./types"

const API_TOKEN_KEY = "apiToken"

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
  const draft = {
    symbol: getInputValue(root, "symbol"),
    providerSymbol: getInputValue(root, "providerSymbol"),
    timeframe: getInputValue(root, "timeframe"),
    tradeDate: getInputValue(root, "tradeDate"),
    decisionTime: getInputValue(root, "decisionTime"),
    priceBasis: getInputValue(root, "priceBasis"),
    sessionState: getInputValue(root, "sessionState"),
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
  for (const field of [
    "symbol",
    "providerSymbol",
    "timeframe",
    "tradeDate",
    "decisionTime",
    "priceBasis",
    "sessionState",
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
