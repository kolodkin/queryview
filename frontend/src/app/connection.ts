import { apiFetch } from './api'

// The active connection as reported by /api/session.

export type Connection = {
  name: string
  type: string
  databases: string[]
  database: string | null
  // The dialect's identifier quote (`"` or a backtick), for dashboard params.
  identQuote?: string
}

// Ready to query when a database is selected, or the driver has no picker
// (empty databases, e.g. DuckDB) so there's nothing to select.
export function isReady(connection: Connection | null): connection is Connection {
  return (
    !!connection && (connection.database !== null || connection.databases.length === 0)
  )
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
  }
}

function postJson(path: string, body: unknown): Promise<Response> {
  return apiFetch(path, {
    method: 'POST',
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

// Select this session's database; false when the switch failed.
export async function selectDatabase(database: string): Promise<boolean> {
  try {
    return (await postJson('/api/db/database', { database })).ok
  } catch {
    return false
  }
}
