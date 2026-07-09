import type { CaptureWorkflow } from "./captureWorkflow"

type ButtonLike = {
  addEventListener: (type: "click", listener: () => void) => void
}

type UtilityActionRoot = {
  querySelector: (selector: string) => ButtonLike | null
}

export type UtilityActionWorkflow = Pick<
  CaptureWorkflow,
  "saveDraftAction" | "retry" | "copyPayload"
>

export const bindUtilityActionButtons = (
  root: UtilityActionRoot,
  workflow: UtilityActionWorkflow,
): void => {
  root.querySelector("[data-save-draft]")?.addEventListener("click", () => {
    void workflow.saveDraftAction()
  })
  root.querySelector("[data-retry-capture]")?.addEventListener("click", () => {
    void workflow.retry()
  })
  root.querySelector("[data-copy-payload]")?.addEventListener("click", () => {
    void workflow.copyPayload()
  })
}
