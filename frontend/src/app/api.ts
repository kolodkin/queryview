// Every /api/* call goes through here so it carries the caller's session. The
// backend resolves `X-QV-Session` into the session whose connection, database
// and workspace the request acts on.

import { SESSION_KEY, TAB_KEY, tabRead } from './tabStorage'

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const sid = tabRead(SESSION_KEY)
  const tab = tabRead(TAB_KEY)
  const headers: Record<string, string> = {
    ...((init.headers as Record<string, string>) ?? {}),
  }
  if (sid) headers['X-QV-Session'] = sid
  // Proves the call comes from the tab holding the session, not an agent that
  // only knows its id (docs/session.md#the-tab-token).
  if (tab) headers['X-QV-Tab'] = tab
  const res = await fetch(path, { ...init, headers })
  if (res.status !== 403 || !sid || !tab) return res
  // A claim that lapsed (a long sleep) refuses every call until the next
  // heartbeat: reclaim it now, as the heartbeat would, and retry once.
  const beat = await fetch('/api/sessions/attach', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tab, session_id: sid, keep: true }),
  })
  return beat.ok ? fetch(path, { ...init, headers }) : res
}
