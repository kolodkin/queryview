// The explorer view's remembered settings (see viewSettings.ts for the
// storage shape). Today that is the Tables sidebar width, so a sidebar dragged
// wide enough for long table names stays that way across reloads.

import { loadViewSettings, patchViewSettings } from './viewSettings'

const VIEW = 'explorer'

export const MIN_SIDEBAR_WIDTH = 200
export const MAX_SIDEBAR_WIDTH = 600
export const DEFAULT_SIDEBAR_WIDTH = 256

// A drag position turned into a usable pixel width. A non-finite drag falls
// back to the default rather than collapsing the panel.
export function clampSidebarWidth(width: number): number {
  if (!Number.isFinite(width)) return DEFAULT_SIDEBAR_WIDTH
  return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, Math.round(width)))
}

export function loadSidebarWidth(): number {
  const stored = loadViewSettings(VIEW).sidebarWidth
  return typeof stored === 'number' ? clampSidebarWidth(stored) : DEFAULT_SIDEBAR_WIDTH
}

export function saveSidebarWidth(width: number): void {
  patchViewSettings(VIEW, { sidebarWidth: clampSidebarWidth(width) })
}
