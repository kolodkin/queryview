// Per-workspace autosave (docs/workspace.md#autosave); the flag itself comes
// from the App shell.

import type { OrderCol } from '../core'

// Fired when the manage panel turns autosave on, so the open view saves what
// it holds unsaved before its Save button disappears.
const AUTOSAVE_ENABLED = 'qv:autosave-enabled'

export function announceAutosaveEnabled(): void {
  window.dispatchEvent(new Event(AUTOSAVE_ENABLED))
}

// Run `f` whenever autosave is turned on; returns the unsubscribe.
export function onAutosaveEnabled(f: () => void): () => void {
  window.addEventListener(AUTOSAVE_ENABLED, f)
  return () => window.removeEventListener(AUTOSAVE_ENABLED, f)
}

type QueryContent = {
  query: string
  cell_view: string | null
  order_by: OrderCol[] | null
  fields: string[] | null
}

// Whether `next` would change the stored row (undefined: none yet), so a re-run
// or page of an unchanged query writes nothing. null and '' both mean "no cell view".
export function queryChanged(saved: QueryContent | undefined, next: QueryContent): boolean {
  if (!saved) return true
  return (
    saved.query !== next.query ||
    (saved.cell_view ?? '') !== (next.cell_view ?? '') ||
    JSON.stringify(saved.order_by ?? null) !== JSON.stringify(next.order_by ?? null) ||
    JSON.stringify(saved.fields ?? null) !== JSON.stringify(next.fields ?? null)
  )
}
