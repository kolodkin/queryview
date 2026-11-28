// The Scripts page's plumbing: which statement the cursor is on, where a
// failed one sits, and the one status line a run leaves.

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

const DOLLAR_TAG = /\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$/y
const MYSQL_CODE_COMMENT = /\/\*!\d*/y // `/*!` and its optional version, as in `/*!50000`

// The index just past the string quoted by `text[i]` opening at `i` (a
// backslash escapes the next character), or the end when it never closes.
function skipQuoted(text: string, i: number): number {
  const quote = text[i]
  for (i += 1; i < text.length; i += 1) {
    if (text[i] === '\\') i += 1
    else if (text[i] === quote) return i + 1
  }
  return text.length
}

// The script with every quote, `$$`/`$tag$` body and `--` or `/* */` comment
// blanked to spaces, keeping its length, so what is left is code. `mysql` reads
// it as MySQL does: `#` starts a comment, `--` only before whitespace, `/*!…*/`
// is code (its `/*!` and version are blanked), `$` is part of a name and `"…"`
// takes backslash escapes. The
// backend's mask_sql; keep the two in step.
function maskSql(text: string, mysql: boolean): string {
  let out = ''
  let last = 0
  let i = 0
  const n = text.length
  while (i < n) {
    const ch = text[i]
    DOLLAR_TAG.lastIndex = i
    MYSQL_CODE_COMMENT.lastIndex = i
    let tag: RegExpExecArray | null
    let opener: RegExpExecArray | null
    let end: number
    if (ch === "'" || (mysql && ch === '"')) {
      end = skipQuoted(text, i)
    } else if (ch === '"' || ch === '`') {
      end = text.indexOf(ch, i + 1)
      end = end < 0 ? n : end + 1
    } else if (!mysql && (tag = DOLLAR_TAG.exec(text)) !== null) {
      end = text.indexOf(tag[0], i + tag[0].length)
      end = end < 0 ? n : end + tag[0].length
    } else if (
      (text.startsWith('--', i) && !(mysql && /\S/.test(text.slice(i + 2, i + 3)))) ||
      (mysql && ch === '#')
    ) {
      end = text.indexOf('\n', i) // the newline itself stays code
      end = end < 0 ? n : end
    } else if (mysql && (opener = MYSQL_CODE_COMMENT.exec(text)) !== null) {
      end = i + opener[0].length
    } else if (text.startsWith('/*', i)) {
      end = text.indexOf('*/', i + 2)
      end = end < 0 ? n : end + 2
    } else {
      i++
      continue
    }
    out += text.slice(last, i) + ' '.repeat(end - i)
    last = i = end
  }
  return out + text.slice(last)
}

// The non-blank statements of a script as character spans — the same split as
// the backend's split_statements, so the statement under the cursor is exactly
// what the server would run alone and the k-th result is the k-th span.
function statementSpans(text: string, mysql: boolean): Span[] {
  const spans: Span[] = []
  const push = (start: number, end: number) => {
    while (start < end && /\s/.test(text[start])) start++
    while (end > start && /\s/.test(text[end - 1])) end--
    if (end > start) spans.push({ start, end })
  }
  const masked = maskSql(text, mysql)
  let start = 0
  for (let i = 0; i < masked.length; i++) {
    if (masked[i] === ';') {
      push(start, i)
      start = i + 1
    }
  }
  push(start, text.length)
  return spans
}

// The statement the cursor is on: the one whose text contains it, else — in
// the gap between two — the previous one while the cursor is still on its
// line (just past the `;`), the next one from a blank line below. Trailing
// whitespace belongs to the last statement. null for a blank script. `mysql`
// splits with MySQL's comments (see maskSql).
export function statementRangeAt(text: string, cursor: number, mysql = false): Span | null {
  const spans = statementSpans(text, mysql)
  if (spans.length === 0) return null
  const inside = spans.find((s) => s.start <= cursor && cursor <= s.end)
  if (inside) return inside
  const prevIdx = spans.findLastIndex((s) => s.end < cursor)
  const next = spans[prevIdx + 1]
  const prev = spans[prevIdx]
  return prev && (!next || !text.slice(prev.end, cursor).includes('\n')) ? prev : next
}

// Where the failing statement of a run sits in the script, for marking it in
// the textbox: `ran` is the text that was sent, starting at `offset`. null when
// nothing failed.
export function failedSpan(
  ran: string,
  offset: number,
  results: StatementResult[],
  mysql = false,
): Span | null {
  const last = results[results.length - 1]
  if (!last || last.ok) return null
  const span = statementSpans(ran, mysql)[results.length - 1]
  return span ? { start: offset + span.start, end: offset + span.end } : null
}

// What a successful statement left: its row count, or the driver's status.
function rowsOrStatus(r: StatementResult): string {
  if (r.data === null) return r.status
  if (r.truncated) return `first ${r.data.length} rows, more exist`
  return `${r.data.length} ${r.data.length === 1 ? 'row' : 'rows'}`
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
  const total = results.reduce((ms, r) => ms + r.elapsed_ms, 0)
  const count = results.length > 1 ? `${results.length} statements · ` : ''
  return { ok: true, text: `${count}${rowsOrStatus(last)} · ${total} ms` }
}
