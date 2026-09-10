// Database-picker filter: case-insensitive substring match on the trimmed
// query, preserving the server's order. A blank query keeps everything.
export function filterDatabases(databases: string[], query: string): string[] {
  const q = query.trim().toLowerCase()
  if (!q) return databases
  return databases.filter((db) => db.toLowerCase().includes(q))
}
