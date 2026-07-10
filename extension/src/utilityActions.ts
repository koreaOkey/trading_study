import type { CaptureWorkflow } from "./captureWorkflow"

type ButtonLike = {
  addEventListener: (type: "click", listener: (event: MouseEvent) => void) => void
}

type UtilityActionRoot = {
  querySelector: (selector: string) => ButtonLike | null
}

export type UtilityActionWorkflow = Pick<
  CaptureWorkflow,
  "submit" | "retryReview"
>

export const bindUtilityActionButtons = (
  root: UtilityActionRoot,
  workflow: UtilityActionWorkflow,
): void => {
  root.querySelector("[data-submit-review]")?.addEventListener("click", (event) => {
    if (event.isTrusted) {
      void workflow.submit()
    }
  })
  root.querySelector("[data-retry-review]")?.addEventListener("click", (event) => {
    if (event.isTrusted) {
      void workflow.retryReview()
    }
  })
}
