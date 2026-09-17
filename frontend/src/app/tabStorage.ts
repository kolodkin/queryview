// The app's only browser-storage touchpoint. `sessionStorage` survives a
// refresh but never crosses to a new tab, which is exactly the distinction the
// session claim needs: a tab that already has an id is refreshing, a tab
// without one is new. It holds identity only — the server holds state.
//
// Access can throw (private windows, blocked site data), so every read and
// write falls back to a module-level map: the tab works normally for its
// lifetime, it just cannot re-attach after a refresh.

export const TAB_KEY = 'qv_tab'
export const SESSION_KEY = 'qv_session'

const memory = new Map<string, string>()

export function tabRead(key: string): string | null {
  try {
    const stored = sessionStorage.getItem(key)
    if (stored !== null) return stored
  } catch {
    /* fall through to the in-memory copy */
  }
  return memory.get(key) ?? null
}

export function tabWrite(key: string, value: string): void {
  memory.set(key, value)
  try {
    sessionStorage.setItem(key, value)
  } catch {
    /* non-persistent contexts still work within the tab's lifetime */
  }
}
