// The Connect page's saved-connection list logic, kept pure for tests.

// A saved connection's card data, from /api/db/connections.
export type SavedConnection = {
  name: string
  type: string
  database: string | null
  last_active_at: number
}

// Past this many saved connections the page switches to its "many" layout:
// search, driver chips, a Recent row and a scrolling list.
export const MANY_THRESHOLD = 6
export const RECENT_COUNT = 3

// Every whitespace-separated term must appear (case-insensitively) in the
// name, driver type, driver label or last database; `type` narrows to one
// driver. Order is kept, so results stay most-recent first.
export function matchConnections(
  list: SavedConnection[],
  query: string,
  type: string | null,
  labelOf: (type: string) => string,
): SavedConnection[] {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
  return list.filter((c) => {
    if (type && c.type !== type) return false
    const hay = [c.name, c.type, labelOf(c.type), c.database ?? ''].join(' ').toLowerCase()
    return terms.every((t) => hay.includes(t))
  })
}

// Driver types present in the list with their counts, most common first.
export function driverCounts(list: SavedConnection[]): [string, number][] {
  const counts = new Map<string, number>()
  for (const c of list) counts.set(c.type, (counts.get(c.type) ?? 0) + 1)
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
}
