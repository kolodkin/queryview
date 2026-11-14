// Every /api/* call goes through here so it carries the caller's session. The
// backend resolves `X-QV-Session` into the session whose connection, database
// and workspace the request acts on.

import { SESSION_KEY, TOKEN_KEY, tabRead } from './tabStorage'

export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const sid = tabRead(SESSION_KEY)
  const headers: Record<string, string> = {
    ...((init.headers as Record<string, string>) ?? {}),
  }
  if (sid) headers['X-QV-Session'] = sid
  const token = tabRead(TOKEN_KEY)
  if (token) headers['X-QV-Token'] = token
  return fetch(path, { ...init, headers })
}

// A JSON request body, POST unless `method` says otherwise.
export function postJson(path: string, body: unknown, method = 'POST'): Promise<Response> {
  return apiFetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
