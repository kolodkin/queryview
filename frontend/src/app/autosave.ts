// Autosave (a per-workspace setting, see docs/workspace.md#autosave): whether
// the active workspace persists on update, and whether a query's current
// content differs from its stored row.

import { useEffect, useState } from 'react'

import type { OrderCol } from '../core'
import { activeWorkspace } from './session'
import { listWorkspaces } from './workspace'

const CHANGED = 'queryview:workspaces-changed'

// Called after workspace settings are saved, so open pages re-read the flag.
export function announceWorkspacesChanged(): void {
  window.dispatchEvent(new Event(CHANGED))
}

// The active workspace's autosave flag; false until known. Pages remount on a
// workspace switch, so only a settings change needs the event.
export function useAutosave(): boolean {
  const [on, setOn] = useState(false)
  useEffect(() => {
    let live = true
    function load() {
      listWorkspaces()
        .then((list) => {
          if (live) setOn(list.find((w) => w.name === activeWorkspace())?.autosave ?? false)
        })
        .catch(() => {})
    }
    load()
    window.addEventListener(CHANGED, load)
    return () => {
      live = false
      window.removeEventListener(CHANGED, load)
    }
  }, [])
  return on
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
