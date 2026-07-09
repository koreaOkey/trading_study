import type { WarningCode } from "./types"

export type OverlayState = {
  readonly status: "checking" | "ready" | "saving" | "saved" | "warning" | "error"
  readonly message: string
  readonly warnings: readonly WarningCode[]
}

export const createElement = <K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text = "",
): HTMLElementTagNameMap[K] => {
  const element = document.createElement(tag)
  element.className = className
  element.textContent = text
  return element
}

export const getInputValue = (root: HTMLElement, name: string): string => {
  const input = root.querySelector<HTMLInputElement>(`[data-field="${name}"]`)
  return input?.value.trim() ?? ""
}

export const getTextareaValue = (root: HTMLElement, name: string): string => {
  const textarea = root.querySelector<HTMLTextAreaElement>(`[data-field="${name}"]`)
  return textarea?.value.trim() ?? ""
}

export const setState = (root: HTMLElement, state: OverlayState): void => {
  const status = root.querySelector<HTMLElement>("[data-status]")
  if (status !== null) {
    status.dataset["status"] = state.status
    status.textContent = state.message
  }
  const warningList = root.querySelector<HTMLElement>("[data-warnings]")
  if (warningList !== null) {
    warningList.replaceChildren(
      ...state.warnings.map((warning) => createElement("span", "fj-warning", warning)),
    )
  }
}

