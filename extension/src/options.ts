import { loadApiToken, saveApiToken } from "./storage"

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8766"

const input = (id: string): HTMLInputElement => {
  const element = document.getElementById(id)
  if (element instanceof HTMLInputElement) {
    return element
  }
  throw new Error(`missing_input:${id}`)
}

const statusElement = (): HTMLElement => {
  const element = document.getElementById("status")
  if (element instanceof HTMLElement) {
    return element
  }
  throw new Error("missing_status")
}

const load = async (): Promise<void> => {
  const [synced, apiToken] = await Promise.all([
    chrome.storage.sync.get(["apiBaseUrl"]),
    loadApiToken(),
  ])
  input("apiBaseUrl").value =
    typeof synced["apiBaseUrl"] === "string" ? synced["apiBaseUrl"] : DEFAULT_API_BASE_URL
  input("apiToken").value = apiToken
}

const save = async (): Promise<void> => {
  await Promise.all([
    chrome.storage.sync.set({
      apiBaseUrl: input("apiBaseUrl").value.trim() || DEFAULT_API_BASE_URL,
    }),
    saveApiToken(input("apiToken").value.trim()),
  ])
  statusElement().textContent = "Saved"
}

document.getElementById("save")?.addEventListener("click", () => {
  void save()
})

void load()
