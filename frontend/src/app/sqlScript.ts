// The Queries page's plumbing: which statement the cursor is on, and the
// one-line summary each statement's result shows.

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

type Span = { start: number; end: number } // the trimmed statement's [start, end)

// The non-blank statements of a script as character spans — the same split the
// backend makes (quotes, `$$` bodies and comments hide their semicolons), so
// "the statement under the cursor" is exactly what the server would run alone.
function statementSpans(text: string): Span[] {
  const spans: Span[] = []
  let start = 0
  let i = 0
  const n = text.length
  const push = (end: number) => {
    let s = start
    let e = end
    while (s < e && /\s/.test(text[s])) s++
    while (e > s && /\s/.test(text[e - 1])) e--
    if (e > s) spans.push({ start: s, end: e })
  }
  while (i < n) {
    const ch = text[i]
    if (ch === "'" || ch === '"' || ch === '`') {
      const end = text.indexOf(ch, i + 1)
      i = end < 0 ? n : end + 1
    } else if (text.startsWith('$$', i)) {
      const end = text.indexOf('$$', i + 2)
      i = end < 0 ? n : end + 2
    } else if (text.startsWith('--', i)) {
      const end = text.indexOf('\n', i)
      i = end < 0 ? n : end + 1
    } else if (text.startsWith('/*', i)) {
      const end = text.indexOf('*/', i + 2)
      i = end < 0 ? n : end + 2
    } else if (ch === ';') {
      push(i)
      start = i + 1
      i++
    } else {
      i++
    }
  }
  push(n)
  return spans
}

// The statement the cursor is on: the one whose text contains it, else — in
// the gap between two — the previous one while the cursor is still on its
// line (just past the `;`), the next one from a blank line below. Trailing
// whitespace belongs to the last statement. '' for a blank script.
export function statementAt(text: string, cursor: number): string {
  const spans = statementSpans(text)
  if (spans.length === 0) return ''
  const inside = spans.find((s) => s.start <= cursor && cursor <= s.end)
  if (inside) return text.slice(inside.start, inside.end)
  const prevIdx = spans.findLastIndex((s) => s.end < cursor)
  const next = spans[prevIdx + 1]
  const prev = spans[prevIdx]
  const pick = prev && (!next || !text.slice(prev.end, cursor).includes('\n')) ? prev : next
  return text.slice(pick.start, pick.end)
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
