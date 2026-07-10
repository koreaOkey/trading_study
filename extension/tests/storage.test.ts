import { beforeEach, describe, expect, test } from "bun:test"

import {
  getSettings,
  loadApiToken,
  manualOverrideValue,
  parseConfirmedOverrides,
  parseStoredCaptureDraft,
  saveApiToken,
} from "../src/storage"

type Store = Record<string, string | undefined>

const installChromeStorage = (syncStore: Store, localStore: Store): void => {
  Object.defineProperty(globalThis, "chrome", {
    configurable: true,
    value: {
      storage: {
        sync: {
          get: async (keys: readonly string[]) =>
            Object.fromEntries(keys.map((key) => [key, syncStore[key]])),
          remove: async (key: string) => {
            delete syncStore[key]
          },
          set: async (values: Store) => {
            Object.assign(syncStore, values)
          },
        },
        local: {
          get: async (keys: readonly string[]) =>
            Object.fromEntries(keys.map((key) => [key, localStore[key]])),
          remove: async (key: string) => {
            delete localStore[key]
          },
          set: async (values: Store) => {
            Object.assign(localStore, values)
          },
        },
      },
    },
  })
}

describe("api token storage", () => {
  beforeEach(() => {
    Reflect.deleteProperty(globalThis, "chrome")
  })

  test("migrates a stale synced token to local storage", async () => {
    // Given
    const syncStore: Store = { apiBaseUrl: "http://127.0.0.1:8766", apiToken: "synced-token" }
    const localStore: Store = {}
    installChromeStorage(syncStore, localStore)

    // When
    const token = await loadApiToken()

    // Then
    expect(token).toBe("synced-token")
    expect(syncStore.apiToken).toBeUndefined()
    expect(localStore.apiToken).toBe("synced-token")
  })

  test("prefers existing local token while removing stale sync token", async () => {
    // Given
    const syncStore: Store = { apiToken: "old-synced-token" }
    const localStore: Store = { apiToken: "local-token" }
    installChromeStorage(syncStore, localStore)

    // When
    const settings = await getSettings()

    // Then
    expect(settings.apiToken).toBe("local-token")
    expect(syncStore.apiToken).toBeUndefined()
    expect(localStore.apiToken).toBe("local-token")
  })

  test("saving a token never leaves it in sync storage", async () => {
    // Given
    const syncStore: Store = { apiToken: "old-synced-token" }
    const localStore: Store = {}
    installChromeStorage(syncStore, localStore)

    // When
    await saveApiToken("new-local-token")

    // Then
    expect(syncStore.apiToken).toBeUndefined()
    expect(localStore.apiToken).toBe("new-local-token")
  })
})

describe("confirmed draft overrides", () => {
  test("stores only values changed from the current automatic candidate", () => {
    // Given
    const automaticSymbol = "214450"

    // When
    const unchanged = manualOverrideValue("214450", automaticSymbol)
    const corrected = manualOverrideValue("214450-KIS", automaticSymbol)

    // Then
    expect(unchanged).toBeUndefined()
    expect(corrected).toBe("214450-KIS")
  })

  test("stores a manual correction when automatic extraction is unavailable", () => {
    // Given
    const automaticSymbol = undefined

    // When
    const corrected = manualOverrideValue("005930", automaticSymbol)

    // Then
    expect(corrected).toBe("005930")
  })

  test("ignores stale legacy candidate fields while restoring explicit overrides", () => {
    // Given
    const legacyDraft = { symbol: "005930", timeframe: "1D" }
    const currentDraft = {
      confirmedOverrides: { symbol: "214450-KIS", decisionTime: "2026-07-09T11:30:00+09:00" },
    }

    // When
    const legacyOverrides = parseConfirmedOverrides(legacyDraft)
    const currentOverrides = parseConfirmedOverrides(currentDraft)

    // Then
    expect(legacyOverrides).toEqual({})
    expect(currentOverrides).toEqual(currentDraft.confirmedOverrides)
  })

  test("migrates a stale legacy note without inventing a crossover hypothesis", () => {
    // Given
    const legacyDraft = {
      confirmedOverrides: { symbol: "005930" },
      decision: "long",
      notes: "SMA50이 SMA200에 접근 중",
      invalidation: "레거시 무효화 메모",
    }

    // When
    const migrated = parseStoredCaptureDraft(legacyDraft)

    // Then
    expect(migrated).toEqual({
      confirmedOverrides: { symbol: "005930" },
      setup: "ma_crossover",
      hypothesis: "uncertain",
      decisionNote: "SMA50이 SMA200에 접근 중",
    })
  })

  test("falls back to uncertain when a stored hypothesis is malformed", () => {
    // Given
    const staleDraft = { hypothesis: "bullish_cross", decisionNote: "검토 필요" }

    // When
    const migrated = parseStoredCaptureDraft(staleDraft)

    // Then
    expect(migrated?.hypothesis).toBe("uncertain")
  })
})
