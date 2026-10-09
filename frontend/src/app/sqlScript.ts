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

export type Span = { start: number; end: number } // the trimmed statement's [start, end)

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
export function statementRangeAt(text: string, cursor: number): Span | null {
  const spans = statementSpans(text)
  if (spans.length === 0) return null
  const inside = spans.find((s) => s.start <= cursor && cursor <= s.end)
  if (inside) return inside
  const prevIdx = spans.findLastIndex((s) => s.end < cursor)
  const next = spans[prevIdx + 1]
  const prev = spans[prevIdx]
  return prev && (!next || !text.slice(prev.end, cursor).includes('\n')) ? prev : next
}

export function statementAt(text: string, cursor: number): string {
  const span = statementRangeAt(text, cursor)
  return span ? text.slice(span.start, span.end) : ''
}

// Where the failing statement of a run sits in the script, for marking it in
// the textbox: `ran` is the text that was sent, starting at `offset` in the
// script, and the server split it exactly as statementSpans does, so the k-th
// result is the k-th span. null when nothing failed.
export function failedSpan(ran: string, offset: number, results: StatementResult[]): Span | null {
  const last = results[results.length - 1]
  if (!last || last.ok) return null
  const span = statementSpans(ran)[results.length - 1]
  return span ? { start: offset + span.start, end: offset + span.end } : null
}

// What a successful statement left: its row count, or the driver's status.
function rowsOrStatus(r: StatementResult): string {
  if (r.data === null) return r.status || 'OK'
  if (r.truncated) return `first ${r.data.length} rows, more exist`
  return `${r.data.length} ${r.data.length === 1 ? 'row' : 'rows'}`
}

export function resultSummary(r: StatementResult): string {
  if (!r.ok) return r.message || 'failed'
  return `${rowsOrStatus(r)} · ${r.elapsed_ms} ms`
}

// The one status line a run leaves under the buttons. The statements are
// already in the textbox, so a run that worked says only how much ran and what
// the last statement left; a run that failed says which statement and why (the
// statement itself is marked in the textbox, see failedSpan).
export function runSummary(results: StatementResult[]): { ok: boolean; text: string } {
  if (results.length === 0) return { ok: true, text: 'Nothing to run' }
  const last = results[results.length - 1]
  if (!last.ok) {
    return { ok: false, text: `Statement #${results.length} Failed - ${last.message || 'failed'}` }
  }
  if (results.length === 1) return { ok: true, text: resultSummary(last) }
  const total = results.reduce((ms, r) => ms + r.elapsed_ms, 0)
  return { ok: true, text: `${results.length} statements · ${rowsOrStatus(last)} · ${total} ms` }
}
