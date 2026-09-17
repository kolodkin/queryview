// The session client: attach/heartbeat/release, the in-memory mirror every view
// reads, and debounced write-back. The server owns the state; this module keeps
// a local copy so the UI renders from it synchronously and a patch in flight is
// never something the user waits on. See docs/session.md.

import { apiFetch } from './api'
import { SESSION_KEY, TAB_KEY, tabRead, tabWrite } from './tabStorage'

export type SessionState = {
  id: string
  label: string
  pinned: boolean
  connection: string | null
  database: string | null
  workspace: string
  url: string
  ui: Record<string, Record<string, unknown>>
}

export type SessionSummary = {
  id: string
  label: string
  pinned: boolean
  connection: string | null
  database: string | null
  held: boolean
  last_active_at: number
}

export type SessionPatch = { url?: string; label?: string; workspace?: string }

// Matches the backend's claim TTL of 30s: a heartbeat every 10s leaves room for
// two missed beats before another tab may take the session.
const HEARTBEAT_MS = 10_000
// Long enough that typing SQL coalesces into one write, short enough that a
// refresh a moment later still finds it.
const DEBOUNCE_MS = 400

let state: SessionState | null = null
let pendingUi: Record<string, Record<string, unknown>> = {}
let pendingFields: SessionPatch = {}
let timer: ReturnType<typeof setTimeout> | undefined
let inFlight: Promise<void> = Promise.resolve()

function tabToken(): string {
  const existing = tabRead(TAB_KEY)
  if (existing) return existing
  const minted = crypto.randomUUID()
  tabWrite(TAB_KEY, minted)
  return minted
}

export function currentSession(): SessionState | null {
  return state
}

export function sessionId(): string | null {
  return state?.id ?? null
}

function adopt(next: SessionState): SessionState {
  state = { ...next, ui: next.ui ?? {} }
  tabWrite(SESSION_KEY, state.id)
  return state
}

export async function attachSession(): Promise<SessionState> {
  const body: Record<string, string> = { tab: tabToken() }
  const known = tabRead(SESSION_KEY)
  if (known) body.session_id = known
  const res = await apiFetch('/api/sessions/attach', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (!data?.session) throw new Error('attach returned no session')
  return adopt(data.session as SessionState)
}

// Re-attaching is the heartbeat: it refreshes the claim without a second
// endpoint, and re-adopts the session if the server handed us a different one.
export function startHeartbeat(): () => void {
  const handle = setInterval(() => void attachSession().catch(() => {}), HEARTBEAT_MS)
  return () => clearInterval(handle)
}

export function releaseSession(): void {
  const tab = tabRead(TAB_KEY)
  if (!tab) return
  const payload = JSON.stringify({ tab })
  try {
    // A beacon survives the page going away; a fetch would be cancelled.
    navigator.sendBeacon?.(
      '/api/sessions/release',
      new Blob([payload], { type: 'application/json' }),
    )
  } catch {
    /* the claim TTL frees the session anyway */
  }
}

function schedule(): void {
  clearTimeout(timer)
  timer = setTimeout(() => void flushPatches(), DEBOUNCE_MS)
}

// Patches are fire-and-forget and last-write-wins: a failed one loses a
// remembered preference, never the user's work in the live tab.
export async function flushPatches(): Promise<void> {
  clearTimeout(timer)
  const sid = state?.id
  const ui = pendingUi
  const fields = pendingFields
  pendingUi = {}
  pendingFields = {}
  if (!sid || (Object.keys(ui).length === 0 && Object.keys(fields).length === 0)) return
  inFlight = apiFetch(`/api/sessions/${encodeURIComponent(sid)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...fields, ...(Object.keys(ui).length ? { ui } : {}) }),
  })
    .then(() => undefined)
    .catch(() => undefined)
  return inFlight
}

export function viewState(view: string): Record<string, unknown> {
  return state?.ui?.[view] ?? {}
}

export function patchView(view: string, changes: Record<string, unknown>): void {
  if (!state) return
  state.ui = { ...state.ui, [view]: { ...(state.ui[view] ?? {}), ...changes } }
  pendingUi = { ...pendingUi, [view]: { ...(pendingUi[view] ?? {}), ...changes } }
  schedule()
}

export function patchSession(changes: SessionPatch, immediate = false): void {
  if (!state) return
  state = { ...state, ...changes } as SessionState
  pendingFields = { ...pendingFields, ...changes }
  if (immediate) void flushPatches()
  else schedule()
}

export async function listSessions(): Promise<SessionSummary[]> {
  const r = await (await apiFetch('/api/sessions')).json()
  return (r.sessions ?? []) as SessionSummary[]
}

// id === null asks for a brand-new session. Returns null when the target is
// open in another tab, which the switcher reports rather than stealing it.
export async function selectSession(id: string | null): Promise<SessionState | null> {
  await flushPatches()
  const res = await apiFetch('/api/sessions/select', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tab: tabToken(), id }),
  })
  const data = await res.json()
  if (!data.ok) return null
  return adopt(data.session as SessionState)
}

export async function removeSession(id: string): Promise<{ ok: boolean; message?: string }> {
  const res = await apiFetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
  return res.json()
}

export async function renameSession(label: string): Promise<void> {
  patchSession({ label }, true)
  await inFlight
}
