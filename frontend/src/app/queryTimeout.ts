// The header's Query timeout chip (docs/queryview.md), kept in the session's
// `ui` blob under the 'app' view. The backend reads it from the session on
// every request, so a change is flushed before the next query can use it.

import { flushPatches, patchView, viewState } from './session'

const VIEW = 'app'

export const DEFAULT_QUERY_TIMEOUT = 30
export const MAX_QUERY_TIMEOUT = 600

export function loadQueryTimeout(): number {
  const stored = viewState(VIEW).queryTimeout
  return typeof stored === 'number' ? stored : DEFAULT_QUERY_TIMEOUT
}

// The typed value, or null for a blank or non-number field (keep the current one).
export function parseQueryTimeout(draft: string): number | null {
  const n = Number(draft)
  return draft.trim() !== '' && Number.isFinite(n) ? n : null
}

// Saves the value clamped to whole seconds in 1..MAX and returns it, after the
// session has it.
export async function saveQueryTimeout(n: number): Promise<number> {
  const clamped = Number.isFinite(n)
    ? Math.min(MAX_QUERY_TIMEOUT, Math.max(1, Math.round(n)))
    : DEFAULT_QUERY_TIMEOUT
  patchView(VIEW, { queryTimeout: clamped })
  await flushPatches()
  return clamped
}
