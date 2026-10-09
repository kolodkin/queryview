// The Queries page's plumbing: what Run sends, and the one-line summary each
// statement's result block shows.

import type { ColumnMeta, Cell } from '../core'

// One statement's outcome from POST /api/db/execute. `meta`/`data` are set for
// a row-returning statement; otherwise `status` is the driver's word for what
// happened (`OK`, Postgres's `INSERT 0 3`). `message` is set when it failed.
export type StatementResult = {
  sql: string
  ok: boolean
  meta: ColumnMeta[] | null
  data: Cell[][] | null
  truncated: boolean
  status: string
  message: string
  elapsed_ms: number
}

// The selection when the user made one, else the whole text — so a page of
// statements can be run one at a time by selecting it.
export function runnableText(value: string, selectionStart: number, selectionEnd: number): string {
  const selected = value.slice(selectionStart, selectionEnd)
  return selected.trim() ? selected : value
}

export function resultSummary(r: StatementResult): string {
  if (!r.ok) return r.message || 'failed'
  const what =
    r.data !== null
      ? r.truncated
        ? `first ${r.data.length} rows, more exist`
        : `${r.data.length} ${r.data.length === 1 ? 'row' : 'rows'}`
      : r.status || 'OK'
  return `${what} · ${r.elapsed_ms} ms`
}
