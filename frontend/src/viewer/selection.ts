// Which connection and dashboard the viewer page opens: the URL first (so a
// shared link opens what it names), then the browser's last pick, then the
// first connection. The server holds no session, so the browser remembers.

export type Selection = { connection: string; dashboard: string }
// What local storage held; null for a half never picked (or storage blocked).
export type StoredSelection = { connection: string | null; dashboard: string | null }

export function pickSelection(
  search: string,
  stored: StoredSelection,
  connections: string[],
  dashboards: string[],
): Selection {
  const url = new URLSearchParams(search)
  const connection =
    [url.get('connection'), stored.connection].find((c) => c && connections.includes(c)) ??
    connections[0] ??
    ''
  // A dashboard the URL names is kept even when unknown: the page says so.
  const named = url.get('name')
  const last = stored.dashboard && dashboards.includes(stored.dashboard) ? stored.dashboard : ''
  return { connection, dashboard: named || last }
}

// The query string a pick is shared as.
export function selectionSearch(sel: Selection): string {
  const params = new URLSearchParams()
  if (sel.connection) params.set('connection', sel.connection)
  if (sel.dashboard) params.set('name', sel.dashboard)
  const text = params.toString()
  return text ? `?${text}` : ''
}

const CONNECTION_KEY = 'qv_viewer_connection'
const DASHBOARD_KEY = 'qv_viewer_dashboard'

// Storage access can throw (private windows, blocked site data): the page then
// just forgets between visits.
export function readStored(): StoredSelection {
  try {
    return {
      connection: localStorage.getItem(CONNECTION_KEY),
      dashboard: localStorage.getItem(DASHBOARD_KEY),
    }
  } catch {
    return { connection: null, dashboard: null }
  }
}

export function writeStored(sel: Selection): void {
  try {
    localStorage.setItem(CONNECTION_KEY, sel.connection)
    localStorage.setItem(DASHBOARD_KEY, sel.dashboard)
  } catch {
    /* non-persistent contexts still work for the visit */
  }
}
