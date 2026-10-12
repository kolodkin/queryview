import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ResultsTable, columnNames, columnTypes, type QueryRows } from '../core'
import { apiFetch } from './api'
import { Spinner } from './controls/Spinner'
import { loadIntoQueryView } from './queryPanel'
import { flushPatches, patchView, viewState } from './session'
import { failedSpan, runSummary, statementRangeAt, type Span, type StatementResult } from './queriesScript'
import { TEXTAREA_SIZES, textareaSizeClass } from './textareaSizes'

// The Queries page (`/queries`, docs/queries.md), mounted by the App shell only
// for a ready connection: a flat SQL textbox whose statements run as written.
// Run takes the statement under the cursor (or the selection), Run all the
// whole script; a run leaves one status line and the last statement's rows.
function QueriesView() {
  const navigate = useNavigate()
  // The text is restored from the session; results never are (docs/session.md).
  const [sql, setSql] = useState(() => {
    const saved = viewState('queries').sql
    return typeof saved === 'string' ? saved : ''
  })
  const [results, setResults] = useState<StatementResult[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rows, setRows] = useState(8)
  // The failing statement of the last run, marked red in the textbox until it
  // is clicked into. Kept with the script it was found in: an edit moves the
  // offsets, so the mark only shows while the text is still what ran.
  const [failed, setFailed] = useState<{ script: string; span: Span } | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const markRef = useRef<HTMLPreElement>(null)
  const runSeq = useRef(0)

  function edit(next: string) {
    setSql(next)
    // Queued for the session; the write lands when the textbox is left.
    patchView('queries', { sql: next })
  }

  // The selection when there is one, else the statement under the cursor.
  function currentStatement(): Span {
    const el = inputRef.current!
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
        const span = failedSpan(text, start, results)
        setFailed(span && { script: sql, span })
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

  const summary = runSummary(results ?? [])
  // The last statement run, when it returned rows: the table below, and what
  // Open in QueryView carries over. A failed statement has no meta.
  const last = results?.at(-1) ?? null
  const lastRows: QueryRows | null = useMemo(
    () => (last?.meta && last.data ? { meta: last.meta, data: last.data } : null),
    [last],
  )
  // Memoized so typing in the textbox doesn't re-render the grid.
  const table = useMemo(
    () =>
      lastRows && (
        <ResultsTable
          columns={columnNames(lastRows)}
          rows={lastRows.data}
          types={columnTypes(lastRows)}
          shownIdx={lastRows.meta.map((_, i) => i)}
          testid="queries-output"
          dimmed={busy}
        />
      ),
    [lastRows, busy],
  )
  const mark = failed && failed.script === sql && rows > 0 ? failed.span : null

  return (
    <div data-testid="queries-page" className="viewport-page flex w-full max-w-[80vw] flex-col">
      <div className="mb-6 flex items-center justify-center">
        <h1 className="text-3xl font-bold tracking-tight text-white [text-shadow:0_2px_30px_rgba(129,140,248,0.45)]">
          Queries
        </h1>
      </div>
      <section className="glass-panel flex grow flex-col gap-3 p-6">
        <div className="flex items-center justify-end gap-1">
          {TEXTAREA_SIZES.map(([label, n]) => (
            <button
              key={label}
              type="button"
              onClick={() => setRows(n)}
              data-testid={`queries-size-${label.toLowerCase()}`}
              className={`glass-toggle px-2 py-1 text-xs ${rows === n ? 'is-active' : ''}`}
            >
              {label}
            </button>
          ))}
        </div>
        {/* The mark is a transparent twin of the textarea laid over it (same
            font, padding, border, wrapping, scroll) with only the failing
            statement painted, so it lands on the same glyphs. */}
        <div className="relative">
          <textarea
            ref={inputRef}
            value={sql}
            onChange={(e) => edit(e.target.value)}
            onFocus={() => setFailed(null)}
            onClick={() => setFailed(null)}
            onKeyDown={onKeyDown}
            onBlur={() => void flushPatches()}
            onScroll={(e) => {
              if (markRef.current) markRef.current.scrollTop = e.currentTarget.scrollTop
            }}
            aria-label="SQL script"
            data-testid="queries-input"
            rows={rows || 1}
            spellCheck={false}
            placeholder={'CREATE TABLE …;\nINSERT INTO …;\nSELECT …'}
            className={`glass-input w-full px-3 font-mono text-sm ${textareaSizeClass(rows)}`}
          />
          {mark && (
            <pre
              ref={markRef}
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words border border-transparent px-3 py-2 font-mono text-sm text-transparent"
            >
              {sql.slice(0, mark.start)}
              <mark data-testid="queries-failed-mark" className="rounded bg-red-500/15 text-red-300">
                {sql.slice(mark.start, mark.end)}
              </mark>
              {sql.slice(mark.end)}
            </pre>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void run(currentStatement())}
            disabled={busy || !sql.trim()}
            data-testid="queries-run-current"
            title="Run the statement under the cursor, or the selection (Ctrl/⌘+Enter)"
            className="glass-btn-primary px-4 py-2 font-semibold"
          >
            ▶ Run
          </button>
          <button
            type="button"
            onClick={() => void run({ start: 0, end: sql.length })}
            disabled={busy || !sql.trim()}
            data-testid="queries-run-all"
            title="Run every statement, in order (Ctrl/⌘+Shift+Enter)"
            className="glass-btn px-3 py-2 text-sm font-medium"
          >
            ▶▶ Run all
          </button>
          <button
            type="button"
            onClick={() => {
              if (!last) return
              loadIntoQueryView(last.sql)
              navigate('/queryview')
            }}
            disabled={!lastRows}
            data-testid="queries-open-queryview"
            title="Load the last statement's SQL into QueryView for paging, saving and presentation"
            className="glass-btn px-3 py-2 text-sm font-medium"
          >
            Open in QueryView
          </button>
          {busy && (
            <span data-testid="queries-busy" role="status" aria-label="Running">
              <Spinner />
            </span>
          )}
          <span className="text-xs text-slate-400">
            Separate statements with <code className="font-mono">;</code>. Run all stops at the
            first error.
          </span>
        </div>
        {error && (
          <p data-testid="queries-error" className="text-sm text-red-300">
            {error}
          </p>
        )}
        {results !== null && (
          <p
            data-testid="queries-status"
            data-ok={summary.ok}
            className={`text-sm ${summary.ok ? 'text-slate-400' : 'text-red-300'}`}
          >
            {summary.text}
          </p>
        )}
        {table}
      </section>
    </div>
  )
}

export default QueriesView
