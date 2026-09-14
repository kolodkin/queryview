// A localStorage fake for unit tests: vitest runs in the node environment, so
// there is no real one. Test-only — nothing reachable from main.tsx imports it.

import { vi } from 'vitest'

// Stub localStorage, optionally pre-loaded with keys. Pair with
// `afterEach(() => vi.unstubAllGlobals())`; the returned map lets a test assert
// on what was written.
export function stubStorage(initial?: Record<string, string>): Map<string, string> {
  const store = new Map<string, string>(Object.entries(initial ?? {}))
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  })
  return store
}

// Stub a localStorage whose every access throws, as a private window or
// blocked site data does.
export function stubBrokenStorage(): void {
  const boom = () => {
    throw new Error('denied')
  }
  vi.stubGlobal('localStorage', { getItem: boom, setItem: boom, removeItem: boom })
}
