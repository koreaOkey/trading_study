import { reclampOverlay } from "./drag"

const MINIMIZED_KEY = "fractalReplayOverlayMinimized"
const MINIMIZED_CLASS = "fj-minimized"

export type MinimizeOrigin = "sheet" | "dock"

type MinimizedPreference = { readonly minimized: boolean; readonly from: MinimizeOrigin }

type PersistMinimized = (preference: MinimizedPreference) => Promise<void>

const persistMinimized: PersistMinimized = async (preference) => {
  await chrome.storage.local.set({ [MINIMIZED_KEY]: preference })
}

export const isOverlayMinimized = (root: HTMLElement): boolean =>
  root.classList.contains(MINIMIZED_CLASS)

export const minimizeOverlay = (
  root: HTMLElement,
  persist: PersistMinimized = persistMinimized,
): void => {
  const from: MinimizeOrigin = root.classList.contains("fj-sheet-open") ? "sheet" : "dock"
  root.dataset["minimizedFrom"] = from
  root.classList.remove("fj-sheet-open")
  root.classList.add(MINIMIZED_CLASS)
  window.requestAnimationFrame(() => reclampOverlay(root))
  void persist({ minimized: true, from })
}

export const restoreOverlay = (
  root: HTMLElement,
  persist: PersistMinimized = persistMinimized,
): MinimizeOrigin => {
  const from: MinimizeOrigin = root.dataset["minimizedFrom"] === "sheet" ? "sheet" : "dock"
  delete root.dataset["minimizedFrom"]
  root.classList.remove(MINIMIZED_CLASS)
  window.requestAnimationFrame(() => reclampOverlay(root))
  void persist({ minimized: false, from })
  return from
}

type ReadMinimized = () => Promise<MinimizedPreference | null>

const readMinimized: ReadMinimized = async () => {
  const stored: unknown = (await chrome.storage.local.get([MINIMIZED_KEY]))[MINIMIZED_KEY]
  // Legacy shape: a bare boolean from before the origin state was remembered.
  if (stored === true) return { minimized: true, from: "dock" }
  if (typeof stored !== "object" || stored === null || !("minimized" in stored)) return null
  const from = "from" in stored && stored.from === "sheet" ? "sheet" : "dock"
  return { minimized: stored.minimized === true, from }
}

export const restoreMinimizedPreference = async (
  root: HTMLElement,
  read: ReadMinimized = readMinimized,
): Promise<void> => {
  const preference = await read()
  if (preference === null || !preference.minimized) return
  root.dataset["minimizedFrom"] = preference.from
  root.classList.add(MINIMIZED_CLASS)
}
