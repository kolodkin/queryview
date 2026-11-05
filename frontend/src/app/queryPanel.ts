import { patchView } from './session'

// Load SQL into the query panel for its next mount (the Scripts page's "Open in
// Studio"): Studio hydrates from this session state, and a fresh query
// gets a fresh presentation — a sort or column pick from the previous one
// would be applied to columns it may not have. Nothing runs until Execute.
export function loadIntoStudio(sql: string): void {
  patchView('query', { sql, visibleCols: [], orderBy: [] })
}
