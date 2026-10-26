import { useEffect, type Dispatch, type SetStateAction } from 'react'

import { apiFetch } from './api'
import { withoutHeartbeat } from './session'
import { TOKEN_KEY, tabWrite } from './tabStorage'

// The active connection as reported by /api/session.

export type Connection = {
  name: string
  type: string
  databases: string[]
  database: string | null
  // The dialect's identifier quote (`"` or a backtick), for dashboard params.
  identQuote?: string
  // False on a locked saved connection this tab holds no token for; the
  // shell prompts for the passphrase while it is.
  unlocked?: boolean
}

// Ready to query when a database is selected, or the driver has no picker
// (empty databases, e.g. DuckDB) so there's nothing to select.
export function isReady(connection: Connection | null): connection is Connection {
  return !!connection && (connection.database !== null || connection.databases.length === 0)
}

// A Connection from an /api/session, /api/db/open or /api/db/connect response.
// What a view's data depends on: the connection and its database together,
// since another connection may select a database of the same name.
export function connectionKey(c: Connection | null): string | null {
  return c ? `${c.name}/${c.database ?? ''}` : null
}

export function toConnection(data: Record<string, unknown>): Connection {
  return {
    name: data.name as string,
    type: (data.type ?? 'clickhouse') as string,
    databases: (data.databases ?? []) as string[],
    database: (data.database ?? null) as string | null,
    identQuote: data.ident_quote as string | undefined,
    unlocked: data.unlocked as boolean | undefined,
  }
}

function postJson(path: string, body: unknown, method = 'POST'): Promise<Response> {
  return apiFetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

// Open a saved connection for this session; it comes back with no database
// selected, so a picker driver lands on the picker.
export async function openSaved(
  name: string,
): Promise<{ ok: true; connection: Connection } | { ok: false; message: string }> {
  try {
    const data = await (await postJson('/api/db/open', { name })).json()
    return data.ok
      ? { ok: true, connection: toConnection(data) }
      : { ok: false, message: data.message ?? `could not open “${name}”` }
  } catch (err) {
    return { ok: false, message: err instanceof Error ? err.message : 'request failed' }
  }
}

export type LockResult = { ok: true } | { ok: false; message: string }

async function lockCall(
  method: string,
  path: string,
  name: string,
  passphrase: string,
): Promise<LockResult> {
  try {
    const data = await (await postJson(path, { name, passphrase }, method)).json()
    if (!data.ok) return { ok: false, message: data.message ?? 'request failed' }
    // Locking and unlocking both hand this tab the connection's unlock token.
    if (typeof data.token === 'string') tabWrite(TOKEN_KEY, data.token)
    return { ok: true }
  } catch (err) {
    return { ok: false, message: err instanceof Error ? err.message : 'request failed' }
  }
}

// Lock a saved connection behind a passphrase (docs/connect.md#locked-connections).
export const lockConnection = (name: string, passphrase: string) =>
  lockCall('POST', '/api/db/lock', name, passphrase)
// Exchange the passphrase for this tab's unlock token on a locked connection.
export const unlockConnection = (name: string, passphrase: string) =>
  lockCall('POST', '/api/db/unlock', name, passphrase)
// Remove a lock for good; takes the passphrase like unlocking does.
export const removeLock = (name: string, passphrase: string) =>
  lockCall('DELETE', '/api/db/lock', name, passphrase)
// Delete a connection; a locked one takes its passphrase.
export const deleteConnection = (name: string, passphrase = '') =>
  lockCall('DELETE', '/api/db/connections', name, passphrase)

// A saved connection's form values (password blank), for editing it. `locked`
// means this tab must unlock it first.
export async function fetchSavedConfig(
  name: string,
): Promise<
  | { ok: true; type: string; values: Record<string, string> }
  | { ok: false; message: string; locked?: boolean }
> {
  try {
    const res = await apiFetch(`/api/db/connections/${encodeURIComponent(name)}`)
    const data = await res.json()
    if (!data.ok)
      return { ok: false, message: data.message ?? 'request failed', locked: res.status === 403 }
    const values = Object.fromEntries(
      Object.entries(data.config as Record<string, unknown>).map(([k, v]) => [k, String(v ?? '')]),
    )
    return { ok: true, type: data.type as string, values: { name, ...values } }
  } catch (err) {
    return { ok: false, message: err instanceof Error ? err.message : 'request failed' }
  }
}

// Select this session's database; false when the switch failed. Held off the
// heartbeat, since the shell follows the row's database (withoutHeartbeat).
export function selectDatabase(database: string): Promise<boolean> {
  return withoutHeartbeat(async () => {
    try {
      return (await postJson('/api/db/database', { database })).ok
    } catch {
      return false
    }
  })
}

// This session's databases, fresh from the server, with the connection they
// belong to; null when the request failed.
async function listDatabases(): Promise<{ name: string; databases: string[] } | null> {
  try {
    const data = await (await apiFetch('/api/db/databases')).json()
    return data.ok ? { name: data.name as string, databases: data.databases as string[] } : null
  } catch {
    return null
  }
}

// While `open` (a database list on screen), re-list once. An unchanged list
// keeps the connection object; a failed re-list keeps the list on screen; a
// list landing after close, or for a connection since left, is dropped.
export function useFreshDatabases(
  open: boolean,
  setConnection: Dispatch<SetStateAction<Connection | null>>,
): void {
  useEffect(() => {
    if (!open) return
    let live = true
    void listDatabases().then((fresh) => {
      if (!live || !fresh) return
      const { name, databases } = fresh
      setConnection((c) => {
        if (!c || c.name !== name) return c
        const same =
          databases.length === c.databases.length && databases.every((d, i) => d === c.databases[i])
        return same ? c : { ...c, databases }
      })
    })
    return () => {
      live = false
    }
  }, [open, setConnection])
}
