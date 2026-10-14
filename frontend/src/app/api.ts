// Every /api/* call goes through here so it carries the caller's session. The
// backend resolves `X-QV-Session` into the session whose connection, database
// and workspace the request acts on.

import { SESSION_KEY, tabRead } from './tabStorage'

export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const sid = tabRead(SESSION_KEY)
  const headers: Record<string, string> = {
    ...((init.headers as Record<string, string>) ?? {}),
  }
  if (sid) headers['X-QV-Session'] = sid
  return fetch(path, { ...init, headers })
}
