// The session client: attach/heartbeat/release, the in-memory mirror every view
// reads, and queued write-back. The server owns the state; this module keeps
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
  connection: string | null
  database: string | null
  held: boolean
}

export type SessionPatch = { url?: string; label?: string; workspace?: string }

// Well inside the backend's 90s claim TTL, which also covers a hidden tab
// throttled to about one beat a minute.
const HEARTBEAT_MS = 10_000
// Flushes queued view state after a pause in editing. A backstop, not the main
// mechanism — the query panel flushes on focus-out and `pagehide` beacons what
// is still pending — so a tab that dies mid-edit loses at most what was typed
// since its last pause.
const IDLE_MS = 5_000

type PendingPatch = SessionPatch & { ui?: Record<string, Record<string, unknown>> }

let state: SessionState | null = null
// Another tab took this session: stop writing to it until the user picks one.
let taken = false
// The heartbeat in flight, if any, and the switches in flight that hold the
// next one off (withoutHeartbeat).
let beating: Promise<void> | null = null
let holds = 0
let pending: PendingPatch = {}
let timer: ReturnType<typeof setTimeout> | undefined
// Subscribers to every row the mirror adopts, whatever brought it.
const rowListeners = new Set<(row: SessionState) => void>()

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

// The workspace the attached session is on. Call sites that only need the name
// — scoping predefined queries, dashboards, export/import — read it here rather
// than threading it through props.
export function activeWorkspace(): string {
  // Empty before attach: the backend then uses its fallback workspace.
  return state?.workspace ?? ''
}

// Every server row lands here — attach, heartbeat, a patch response, a switch.
function adopt(next: SessionState): SessionState {
  state = { ...next, ui: next.ui ?? {} }
  tabWrite(SESSION_KEY, state.id)
  for (const f of rowListeners) f(state)
  return state
}

// Run `f` on every row adopted from here on; returns the unsubscribe. The
// shell uses it to notice a connection or database switched elsewhere.
export function onSessionRow(f: (row: SessionState) => void): () => void {
  rowListeners.add(f)
  return () => void rowListeners.delete(f)
}

export class SessionTakenError extends Error {}

// `keep` is the heartbeat's form: a session another live tab now holds is
// reported (409) rather than swapped for a different one.
export async function attachSession(keep = false): Promise<SessionState> {
  const body: Record<string, unknown> = { tab: tabToken() }
  const known = tabRead(SESSION_KEY)
  if (known) body.session_id = known
  if (keep) body.keep = true
  const res = await apiFetch('/api/sessions/attach', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (keep && res.status === 409) throw new SessionTakenError()
  const data = await res.json()
  if (!data?.session) throw new Error('attach returned no session')
  return adopt(data.session as SessionState)
}

export function isTaken(): boolean {
  return taken
}

export type HeartbeatEvents = {
  // The server handed this tab a different session (its own was deleted).
  onChanged: (next: SessionState) => void
  // Another tab took this session; the tab stops beating and writing.
  onTaken: () => void
}

// Re-attaching is the heartbeat: it refreshes the claim without a second
// endpoint. It also beats when the tab becomes visible, since a hidden tab's
// timers are throttled and its claim may have lapsed meanwhile.
export function startHeartbeat(events: HeartbeatEvents): () => void {
  let last = Date.now()
  const run = async () => {
    const before = state?.id
    try {
      const next = await attachSession(true)
      if (next.id !== before) events.onChanged(next)
    } catch (e) {
      if (!(e instanceof SessionTakenError)) return
      taken = true
      pending = {}
      clearTimeout(timer)
      events.onTaken()
    }
  }
  const beat = async () => {
    if (taken || beating || holds > 0) return
    last = Date.now()
    beating = run().finally(() => {
      beating = null
    })
    await beating
  }
  const handle = setInterval(() => void beat(), HEARTBEAT_MS)
  // Only a beat overdue by the interval can have let the claim lapse.
  const onVisible = () => {
    if (document.visibilityState === 'visible' && Date.now() - last >= HEARTBEAT_MS) void beat()
  }
  document.addEventListener('visibilitychange', onVisible)
  return () => {
    clearInterval(handle)
    document.removeEventListener('visibilitychange', onVisible)
  }
}

// The closing tab's last word. It carries whatever is still queued, because
// `pagehide` also fires on a reload: a sidebar dragged or a query
// typed a moment ago must survive it. A beacon survives the page going away;
// the in-flight fetch a normal patch uses would be cancelled.
export function releaseSession(): void {
  const tab = tabRead(TAB_KEY)
  if (!tab) return
  clearTimeout(timer)
  const payload: Record<string, unknown> = { tab, ...pending }
  // The URL goes along even when it isn't pending: a navigation's own PATCH
  // may still be in flight, and the unload cancels it.
  if (state?.id && !taken) Object.assign(payload, { session_id: state.id, url: state.url })
  pending = {}
  try {
    navigator.sendBeacon?.(
      '/api/sessions/release',
      new Blob([JSON.stringify(payload)], { type: 'application/json' }),
    )
  } catch {
    /* the claim TTL frees the session anyway */
  }
}

function schedule(): void {
  clearTimeout(timer)
  timer = setTimeout(() => void flushPatches(), IDLE_MS)
}

// Patches are fire-and-forget and last-write-wins: a failed one loses a
// remembered preference, never the user's work in the live tab. The response
// carries the updated session, so server-derived values (a label an empty name
// unpinned) land back in the mirror.
export async function flushPatches(): Promise<void> {
  clearTimeout(timer)
  const sid = state?.id
  const body = pending
  pending = {}
  if (!sid || taken || Object.keys(body).length === 0) return
  try {
    const res = await apiFetch(`/api/sessions/${encodeURIComponent(sid)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    if (data?.session) adopt(data.session as SessionState)
  } catch {
    /* a lost patch costs a remembered preference, never live work */
  }
}

// Runs a switch of session, connection or database with no heartbeat
// overlapping it: the beat in flight lands first, none starts until `f`
// settles. A beat straddling the switch would adopt the row from before it —
// claiming the old session back, or handing the shell the old database.
export async function withoutHeartbeat<T>(f: () => Promise<T>): Promise<T> {
  holds++
  try {
    await beating
    return await f()
  } finally {
    holds--
  }
}

export function viewState(view: string): Record<string, unknown> {
  return state?.ui?.[view] ?? {}
}

// Queues a view's change for the idle backstop, or for an earlier flushPatches()
// from a view that knows when the user is done.
export function patchView(view: string, changes: Record<string, unknown>): void {
  if (!state) return
  state.ui = { ...state.ui, [view]: { ...(state.ui[view] ?? {}), ...changes } }
  pending.ui = { ...pending.ui, [view]: { ...(pending.ui?.[view] ?? {}), ...changes } }
  schedule()
}

// Row fields are discrete acts — a navigation, a workspace switch, a rename —
// so they flush at once rather than queueing.
export function patchSession(changes: SessionPatch): Promise<void> {
  if (!state) return Promise.resolve()
  state = { ...state, ...changes } as SessionState
  pending = { ...pending, ...changes }
  return flushPatches()
}

export async function listSessions(): Promise<SessionSummary[]> {
  const r = await (await apiFetch('/api/sessions')).json()
  return (r.sessions ?? []) as SessionSummary[]
}

// id === null asks for a brand-new session. Returns null when the target is
// open in another tab, which the switcher reports rather than stealing it —
// unless `force` takes it over (the other tab then finds it taken).
export function selectSession(id: string | null, force = false): Promise<SessionState | null> {
  return withoutHeartbeat(async () => {
    await flushPatches()
    const res = await apiFetch('/api/sessions/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tab: tabToken(), id, force }),
    })
    const data = await res.json()
    if (!data.ok) return null
    taken = false
    return adopt(data.session as SessionState)
  })
}

export async function removeSession(id: string): Promise<{ ok: boolean; message?: string }> {
  const res = await apiFetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
  return res.json()
}

// Returns the label the server settled on: clearing the name unpins, and the
// derived label comes back on the patch response.
export async function renameSession(label: string): Promise<string> {
  await patchSession({ label })
  return state?.label ?? label
}
