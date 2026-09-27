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
export function isReady(connection: Connection | null): boolean {
  return (
    !!connection && (connection.database !== null || connection.databases.length === 0)
  )
}
