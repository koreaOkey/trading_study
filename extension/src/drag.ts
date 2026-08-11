export type Point = {
  readonly x: number
  readonly y: number
}

export type Size = {
  readonly width: number
  readonly height: number
}

const POSITION_KEY = "fractalReplayOverlayPosition"
const VIEWPORT_MARGIN = 8
// Generous dead zone: a physical trackpad press wobbles the pointer a few
// pixels, and that wobble must still count as a click on the bubble.
const DRAG_CLICK_SLOP_PX = 8

export const clampOverlayPosition = (
  position: Point,
  overlay: Size,
  viewport: Size,
  margin: number,
): Point => ({
  x: Math.min(Math.max(margin, position.x), Math.max(margin, viewport.width - overlay.width - margin)),
  y: Math.min(Math.max(margin, position.y), Math.max(margin, viewport.height - overlay.height - margin)),
})

const viewportSize = (): Size => ({ width: window.innerWidth, height: window.innerHeight })

const overlaySize = (root: HTMLElement): Size => {
  const rect = root.getBoundingClientRect()
  return { width: rect.width, height: rect.height }
}

const readStoredPoint = (value: unknown): Point | null => {
  if (typeof value !== "object" || value === null || !("x" in value) || !("y" in value)) {
    return null
  }
  const x = value.x
  const y = value.y
  return typeof x === "number" && typeof y === "number" ? { x, y } : null
}

const applyPosition = (root: HTMLElement, position: Point): void => {
  root.classList.add("fj-positioned")
  root.style.left = `${position.x}px`
  root.style.top = `${position.y}px`
  root.style.right = "auto"
  root.style.bottom = "auto"
}

export const reclampOverlay = (root: HTMLElement): void => {
  if (!root.classList.contains("fj-positioned")) {
    return
  }
  const rect = root.getBoundingClientRect()
  applyPosition(
    root,
    clampOverlayPosition(
      { x: rect.left, y: rect.top },
      overlaySize(root),
      viewportSize(),
      VIEWPORT_MARGIN,
    ),
  )
}

type ResizeObserverPort = {
  readonly observe: (target: Element) => void
}

type ResizeObserverFactory = (callback: () => void) => ResizeObserverPort

const defaultResizeObserverFactory: ResizeObserverFactory = (callback) =>
  new ResizeObserver(() => callback())

export const bindOverlayResizeReclamp = (
  root: HTMLElement,
  createObserver: ResizeObserverFactory = defaultResizeObserverFactory,
): void => {
  const observer = createObserver(() => reclampOverlay(root))
  observer.observe(root)
}

const persistPosition = async (root: HTMLElement): Promise<void> => {
  const rect = root.getBoundingClientRect()
  await chrome.storage.local.set({ [POSITION_KEY]: { x: rect.left, y: rect.top } })
}

const restorePosition = async (root: HTMLElement): Promise<void> => {
  const stored = await chrome.storage.local.get([POSITION_KEY])
  const point = readStoredPoint(stored[POSITION_KEY])
  if (point === null) {
    return
  }
  applyPosition(
    root,
    clampOverlayPosition(point, overlaySize(root), viewportSize(), VIEWPORT_MARGIN),
  )
}

const isInteractiveTarget = (target: EventTarget | null): boolean => {
  if (!(target instanceof Element)) {
    return false
  }
  const interactive = target.closest("button, input, textarea, select, a")
  return interactive !== null && !interactive.hasAttribute("data-drag-handle")
}

// A handle that is itself a button (the minimized bubble) fires a click when a
// drag ends; callers consume this flag to tell that click from a deliberate press.
export const consumeDragClick = (root: HTMLElement): boolean => {
  const moved = root.dataset["dragMoved"] === "true"
  delete root.dataset["dragMoved"]
  return moved
}

export const bindDraggableOverlay = async (root: HTMLElement): Promise<void> => {
  let pointerId: number | null = null
  let pointerOffset: Point = { x: 0, y: 0 }
  let dragOrigin: Point = { x: 0, y: 0 }

  root.querySelectorAll<HTMLElement>("[data-drag-handle]").forEach((handle) => {
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || isInteractiveTarget(event.target)) {
        return
      }
      const rect = root.getBoundingClientRect()
      pointerId = event.pointerId
      pointerOffset = { x: event.clientX - rect.left, y: event.clientY - rect.top }
      dragOrigin = { x: event.clientX, y: event.clientY }
      delete root.dataset["dragMoved"]
      handle.setPointerCapture(event.pointerId)
      root.classList.add("fj-dragging")
      event.preventDefault()
    })
    handle.addEventListener("pointermove", (event) => {
      if (pointerId !== event.pointerId) {
        return
      }
      if (root.dataset["dragMoved"] !== "true") {
        const slop =
          Math.abs(event.clientX - dragOrigin.x) + Math.abs(event.clientY - dragOrigin.y)
        if (slop <= DRAG_CLICK_SLOP_PX) {
          return
        }
        root.dataset["dragMoved"] = "true"
      }
      applyPosition(
        root,
        clampOverlayPosition(
          { x: event.clientX - pointerOffset.x, y: event.clientY - pointerOffset.y },
          overlaySize(root),
          viewportSize(),
          VIEWPORT_MARGIN,
        ),
      )
    })
    const finishDrag = (event: PointerEvent): void => {
      if (pointerId !== event.pointerId) {
        return
      }
      pointerId = null
      root.classList.remove("fj-dragging")
      void persistPosition(root)
    }
    handle.addEventListener("pointerup", finishDrag)
    handle.addEventListener("pointercancel", finishDrag)
  })

  window.addEventListener("resize", () => reclampOverlay(root))
  bindOverlayResizeReclamp(root)
  await restorePosition(root)
}
