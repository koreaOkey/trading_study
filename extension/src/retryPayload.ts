import { capturePayloadSchema } from "./types"
import type { CapturePayload } from "./types"

const RETRY_PAYLOAD_KEY = "fractalReplayRetryPayload"

export const clearRetryPayload = async (): Promise<void> => {
  await chrome.storage.local.remove(RETRY_PAYLOAD_KEY)
}

export const loadRetryPayload = async (): Promise<CapturePayload | null> => {
  const stored = await chrome.storage.local.get([RETRY_PAYLOAD_KEY])
  const parsed = capturePayloadSchema.safeParse(stored[RETRY_PAYLOAD_KEY])
  if (parsed.success) {
    return parsed.data
  }
  if (stored[RETRY_PAYLOAD_KEY] !== undefined) {
    await clearRetryPayload()
  }
  return null
}

export const storeRetryPayload = async (payload: CapturePayload): Promise<void> => {
  await chrome.storage.local.set({ [RETRY_PAYLOAD_KEY]: payload })
}

export const copyText = async (text: string): Promise<void> => {
  if (navigator.clipboard !== undefined) {
    await navigator.clipboard.writeText(text)
    return
  }
  const textarea = document.createElement("textarea")
  textarea.value = text
  textarea.style.position = "fixed"
  textarea.style.left = "-9999px"
  document.body.append(textarea)
  textarea.select()
  const copied = document.execCommand("copy")
  textarea.remove()
  if (!copied) {
    throw new Error("copy_failed")
  }
}
