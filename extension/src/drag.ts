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

const isInteractiveTarget = (target: EventTarget | null): boolean =>
  target instanceof Element && target.closest("button, input, textarea, select, a") !== null

export const bindDraggableOverlay = async (root: HTMLElement): Promise<void> => {
  let pointerId: number | null = null
  let pointerOffset: Point = { x: 0, y: 0 }

  root.querySelectorAll<HTMLElement>("[data-drag-handle]").forEach((handle) => {
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || isInteractiveTarget(event.target)) {
        return
      }
      const rect = root.getBoundingClientRect()
      pointerId = event.pointerId
      pointerOffset = { x: event.clientX - rect.left, y: event.clientY - rect.top }
      handle.setPointerCapture(event.pointerId)
      root.classList.add("fj-dragging")
      event.preventDefault()
    })
    handle.addEventListener("pointermove", (event) => {
      if (pointerId !== event.pointerId) {
        return
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
  await restorePosition(root)
}
