import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ResultsTable, columnNames, columnTypes, type QueryRows } from '../core'
import { apiFetch } from './api'
import { Spinner } from './controls/Spinner'
import { flushPatches, patchView, viewState } from './session'
import {
  failedSpan,
  runSummary,
  statementRangeAt,
  type Span,
  type StatementResult,
} from './sqlScript'

// The Queries page (`/sql`), mounted by the App shell only for a ready
// connection: one flat SQL textbox whose `;`-separated statements run as
// written — writes and DDL included, no pagination, nothing saved. Run runs
// the statement under the cursor (or the selection), Run all the whole script.
// A run leaves one status line; the last statement's rows, if any, are the
// table below, and Open in QueryView carries that statement over (docs/sql.md).
// The same height steps as QueryView's textarea.
const SIZES: [string, number, string][] = [
  ['Min', 0, 'sql-size-min'],
  ['S', 4, 'sql-size-s'],
  ['M', 8, 'sql-size-m'],
  ['L', 16, 'sql-size-l'],
  ['XL', 28, 'sql-size-xl'],
]

function SqlView({ runOn }: { runOn?: string | null }) {
  const navigate = useNavigate()
  // The text is restored from the session; results never are (docs/session.md).
  const saved = viewState('sql')
  const [sql, setSql] = useState(() => (typeof saved.sql === 'string' ? saved.sql : ''))
  const [results, setResults] = useState<StatementResult[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Textarea height in rows; Min collapses it so the rows below get the room.
  const [rows, setRows] = useState(8)
  // The failing statement of the last run, marked red in the textbox until
  // the textbox is focused or edited — the status line then needn't repeat it.
  const [failed, setFailed] = useState<Span | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const markRef = useRef<HTMLPreElement>(null)
  const runSeq = useRef(0)

  // Queue the text for the session; the write lands when the textbox is left.
  // The first run is skipped: it would patch the row with what it just read.
  const restored = useRef(true)
  useEffect(() => {
    if (restored.current) {
      restored.current = false
      return
    }
    patchView('sql', { sql })
  }, [sql])

  // A database switch invalidates what is on screen: the rows came from
  // somewhere else now. The text stays — it is the user's.
  const firstScope = useRef(true)
  useEffect(() => {
    if (firstScope.current) {
      firstScope.current = false
      return
    }
    setResults(null)
    setError(null)
  }, [runOn])

  // The selection when there is one, else the statement under the cursor.
  function currentStatement(): Span {
    const el = inputRef.current
    if (!el) return { start: 0, end: sql.length }
    if (sql.slice(el.selectionStart, el.selectionEnd).trim()) {
      return { start: el.selectionStart, end: el.selectionEnd }
    }
    return statementRangeAt(sql, el.selectionStart) ?? { start: 0, end: 0 }
  }

  // Runs the script's [start, end) slice.
  async function run({ start, end }: Span) {
    const text = sql.slice(start, end)
    if (!text.trim() || busy) return
    const ticket = ++runSeq.current
    setBusy(true)
    setError(null)
    setFailed(null)
    try {
      const res = await apiFetch('/api/db/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql: text }),
      })
      const data = await res.json()
      if (ticket !== runSeq.current) return
      if (data.ok) {
        const results = (data.results ?? []) as StatementResult[]
        setResults(results)
        // Only while the script is still what ran: an edit moved the offsets.
        if (inputRef.current?.value === sql) setFailed(failedSpan(text, start, results))
      } else {
        setError((data.message as string) ?? 'request failed')
      }
    } catch (err) {
      if (ticket !== runSeq.current) return
      setError(err instanceof Error ? err.message : 'request failed')
    } finally {
      if (ticket === runSeq.current) setBusy(false)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      void run(e.shiftKey ? { start: 0, end: sql.length } : currentStatement())
    }
  }

  // The last statement run, when it returned rows: the table below, and what
  // Open in QueryView carries over.
  const last = results && results.length > 0 ? results[results.length - 1] : null
  const lastRows: QueryRows | null = useMemo(
    () => (last && last.ok && last.meta && last.data ? { meta: last.meta, data: last.data } : null),
    [last],
  )
  const summary = useMemo(() => runSummary(results ?? []), [results])
  const columns = useMemo(() => (lastRows ? columnNames(lastRows) : []), [lastRows])
  const types = useMemo(() => (lastRows ? columnTypes(lastRows) : {}), [lastRows])
  const shownIdx = useMemo(() => columns.map((_, i) => i), [columns])

  // QueryView hydrates its SQL from the session on mount, so write the
  // statement there first and then go.
  async function openInQueryView() {
    if (!last || !lastRows) return
    patchView('query', { sql: last.sql })
    await flushPatches()
    navigate('/queries')
  }

  return (
    <div data-testid="sql-page" className="viewport-page flex w-full max-w-[80vw] flex-col">
      <div className="mb-6 flex items-center justify-center">
        <h1 className="text-3xl font-bold tracking-tight text-white [text-shadow:0_2px_30px_rgba(129,140,248,0.45)]">
          Queries
        </h1>
      </div>
      <section className="glass-panel flex grow flex-col gap-3 p-6">
        <div className="flex items-center justify-end gap-1">
          {SIZES.map(([label, n, testid]) => (
            <button
              key={testid}
              type="button"
              onClick={() => setRows(n)}
              data-testid={testid}
              className={`glass-toggle px-2 py-1 text-xs ${rows === n ? 'is-active' : ''}`}
            >
              {label}
            </button>
          ))}
        </div>
        {/* The mark is a transparent twin of the textarea laid over it — same
            font, padding, border and wrapping, scrolled in step — with only
            the failing statement painted, so it lands on the same glyphs. */}
        <div className="relative">
          <textarea
            ref={inputRef}
            value={sql}
            onChange={(e) => {
              setFailed(null)
              setSql(e.target.value)
            }}
            onFocus={() => setFailed(null)}
            onClick={() => setFailed(null)}
            onKeyDown={onKeyDown}
            onBlur={() => void flushPatches()}
            onScroll={(e) => {
              if (markRef.current) markRef.current.scrollTop = e.currentTarget.scrollTop
            }}
            aria-label="SQL script"
            data-testid="sql-input"
            rows={rows || 1}
            spellCheck={false}
            placeholder={'CREATE TABLE …;\nINSERT INTO …;\nSELECT …'}
            className={`glass-input w-full px-3 font-mono text-sm ${
              rows === 0 ? 'h-0 min-h-0 overflow-hidden border-transparent py-0' : 'py-2'
            }`}
          />
          {failed && rows > 0 && (
            <pre
              ref={markRef}
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words border border-transparent px-3 py-2 font-mono text-sm text-transparent"
            >
              {sql.slice(0, failed.start)}
              <mark data-testid="sql-failed-mark" className="rounded bg-red-500/15 text-red-300">
                {sql.slice(failed.start, failed.end)}
              </mark>
              {sql.slice(failed.end)}
            </pre>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void run(currentStatement())}
            disabled={busy || !sql.trim()}
            data-testid="sql-run-current"
            title="Run the statement under the cursor, or the selection (Ctrl/⌘+Enter)"
            className="glass-btn-primary px-4 py-2 font-semibold"
          >
            ▶ Run
          </button>
          <button
            type="button"
            onClick={() => void run({ start: 0, end: sql.length })}
            disabled={busy || !sql.trim()}
            data-testid="sql-run-all"
            title="Run every statement, in order (Ctrl/⌘+Shift+Enter)"
            className="glass-btn px-3 py-2 text-sm font-medium"
          >
            ▶▶ Run all
          </button>
          <button
            type="button"
            onClick={() => void openInQueryView()}
            disabled={!lastRows}
            data-testid="sql-open-queryview"
            title="Load the last statement's SQL into QueryView for paging, saving and presentation"
            className="glass-btn px-3 py-2 text-sm font-medium"
          >
            Open in QueryView
          </button>
          {busy && (
            <span data-testid="sql-busy" role="status" aria-label="Running">
              <Spinner />
            </span>
          )}
          <span className="text-xs text-slate-400">
            Separate statements with <code className="font-mono">;</code>. Run all stops at the
            first error.
          </span>
        </div>
        {error && (
          <p data-testid="sql-error" className="text-sm text-red-300">
            {error}
          </p>
        )}
        {results !== null && (
          <p
            data-testid="sql-status"
            data-ok={summary.ok}
            className={`text-sm ${summary.ok ? 'text-slate-400' : 'text-red-300'}`}
          >
            {summary.text}
          </p>
        )}
        {lastRows && (
          <ResultsTable
            columns={columns}
            rows={lastRows.data}
            types={types}
            shownIdx={shownIdx}
            testid="sql-output"
            dimmed={busy}
          />
        )}
      </section>
    </div>
  )
}

export default SqlView
