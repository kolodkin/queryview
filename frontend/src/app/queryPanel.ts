import { patchView } from './session'

// Load SQL into the query panel for its next mount (the Queries page's "Open in
// QueryView"): QueryView hydrates from this session state, and a fresh query
// gets a fresh presentation — a sort or column pick from the previous one
// would be applied to columns it may not have. Nothing runs until Execute.
export function loadIntoQueryView(sql: string): void {
  patchView('query', { sql, visibleCols: [], orderBy: [] })
}
