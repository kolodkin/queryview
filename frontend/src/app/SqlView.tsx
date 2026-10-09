import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ResultsTable, columnNames, columnTypes, type QueryRows } from '../core'
import { apiFetch } from './api'
import { Spinner } from './controls/Spinner'
import { flushPatches, patchView, viewState } from './session'
import { resultSummary, statementAt, type StatementResult } from './sqlScript'

// The Queries page (`/sql`), mounted by the App shell only for a ready
// connection: one flat SQL textbox whose `;`-separated statements run as
// written — writes and DDL included, no pagination, nothing saved. Run runs
// the statement under the cursor (or the selection), Run all the whole script.
// Every statement gets a log line; the last one's rows, if any, are the table
// below, and Open in QueryView carries that statement over (docs/sql.md).
function SqlView({ runOn }: { runOn?: string | null }) {
  const navigate = useNavigate()
  // The text is restored from the session; results never are (docs/session.md).
  const saved = viewState('sql')
  const [sql, setSql] = useState(() => (typeof saved.sql === 'string' ? saved.sql : ''))
  const [results, setResults] = useState<StatementResult[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
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
  function currentStatement(): string {
    const el = inputRef.current
    if (!el) return sql
    const selected = sql.slice(el.selectionStart, el.selectionEnd)
    return selected.trim() ? selected : statementAt(sql, el.selectionStart)
  }

  async function run(text: string) {
    if (!text.trim() || busy) return
    const ticket = ++runSeq.current
    setBusy(true)
    setError(null)
    try {
      const res = await apiFetch('/api/db/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql: text }),
      })
      const data = await res.json()
      if (ticket !== runSeq.current) return
      if (data.ok) {
        setResults((data.results ?? []) as StatementResult[])
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
      void run(e.shiftKey ? sql : currentStatement())
    }
  }

  // The last statement run, when it returned rows: the table below, and what
  // Open in QueryView carries over.
  const last = results && results.length > 0 ? results[results.length - 1] : null
  const lastRows: QueryRows | null = useMemo(
    () => (last && last.ok && last.meta && last.data ? { meta: last.meta, data: last.data } : null),
    [last],
  )
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
        <textarea
          ref={inputRef}
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => void flushPatches()}
          aria-label="SQL script"
          data-testid="sql-input"
          rows={10}
          spellCheck={false}
          placeholder={'CREATE TABLE …;\nINSERT INTO …;\nSELECT …'}
          className="glass-input w-full resize-y px-3 py-2 font-mono text-sm"
        />
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
            onClick={() => void run(sql)}
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
          <ol data-testid="sql-results" className="flex flex-col gap-1">
            {results.map((r, i) => (
              <li
                key={i}
                data-testid="sql-result"
                data-ok={r.ok}
                className={`flex flex-wrap items-baseline gap-x-3 rounded-lg border px-3 py-1.5 ${
                  r.ok ? 'border-white/10 bg-white/[0.02]' : 'border-red-400/40 bg-red-500/5'
                }`}
              >
                <code
                  data-testid="sql-result-sql"
                  title={r.sql}
                  className="min-w-0 max-w-full truncate font-mono text-xs text-slate-300"
                >
                  {r.sql.replace(/\s+/g, ' ')}
                </code>
                {r.ok ? (
                  <span
                    data-testid="sql-result-status"
                    className="shrink-0 text-xs text-slate-400"
                  >
                    {resultSummary(r)}
                  </span>
                ) : (
                  <span data-testid="sql-result-error" className="text-sm text-red-300">
                    {resultSummary(r)}
                  </span>
                )}
              </li>
            ))}
          </ol>
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
