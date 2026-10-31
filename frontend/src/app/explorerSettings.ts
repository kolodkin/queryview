// The explorer's remembered settings, kept in the session's `ui` blob under
// the 'explorer' view (session.ts holds the storage shape).
// The Tables sidebar width, so a sidebar dragged wide enough for long table
// names stays that way, and the DuckDB folder mode's union-by-name flag.

import { patchView, viewState } from './session'

const VIEW = 'explorer'

export const MIN_SIDEBAR_WIDTH = 200
export const MAX_SIDEBAR_WIDTH = 600
export const DEFAULT_SIDEBAR_WIDTH = 256

// A drag position as a usable pixel width; a non-finite drag falls back to the
// default rather than collapsing the panel.
export function clampSidebarWidth(width: number): number {
  if (!Number.isFinite(width)) return DEFAULT_SIDEBAR_WIDTH
  return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, Math.round(width)))
}

export function loadSidebarWidth(): number {
  const stored = viewState(VIEW).sidebarWidth
  return typeof stored === 'number' ? clampSidebarWidth(stored) : DEFAULT_SIDEBAR_WIDTH
}

export function saveSidebarWidth(width: number): void {
  patchView(VIEW, { sidebarWidth: clampSidebarWidth(width) })
}

// Folder mode's list limit: folders scanned and files listed per folder. The
// backend reads it from the session, so it must be flushed before a re-list.
export const DEFAULT_MAX_ENTRIES = 1000
export const MAX_MAX_ENTRIES = 100_000

export function loadMaxEntries(): number {
  const stored = viewState(VIEW).maxEntries
  return typeof stored === 'number' ? stored : DEFAULT_MAX_ENTRIES
}

// The typed value, or null for a blank or non-number field (keep the current one).
export function parseMaxEntries(draft: string): number | null {
  const n = Number(draft)
  return draft.trim() !== '' && Number.isFinite(n) ? n : null
}

export function saveMaxEntries(n: number): number {
  const clamped = Number.isFinite(n)
    ? Math.min(MAX_MAX_ENTRIES, Math.max(1, Math.round(n)))
    : DEFAULT_MAX_ENTRIES
  patchView(VIEW, { maxEntries: clamped })
  return clamped
}

// Whether folder-mode glob entries match columns by name across files.
export function loadUnionByName(): boolean {
  return viewState(VIEW).unionByName === true
}

export function saveUnionByName(on: boolean): void {
  patchView(VIEW, { unionByName: on })
}
