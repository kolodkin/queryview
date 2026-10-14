// Every /api/* call goes through here so it carries the caller's session. The
// backend resolves `X-QV-Session` into the session whose connection, database
// and workspace the request acts on.

import { SESSION_KEY, TAB_KEY, tabRead } from './tabStorage'

export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const sid = tabRead(SESSION_KEY)
  const headers: Record<string, string> = {
    ...((init.headers as Record<string, string>) ?? {}),
  }
  if (sid) headers['X-QV-Session'] = sid
  // Proves the call comes from the tab holding the session, not an agent that
  // only knows its id (docs/connect.md#session-connections).
  const tab = tabRead(TAB_KEY)
  if (tab) headers['X-QV-Tab'] = tab
  return fetch(path, { ...init, headers })
}
