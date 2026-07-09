import { beforeEach, describe, expect, test } from "bun:test"

import { getSettings, loadApiToken, saveApiToken } from "../src/storage"

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
