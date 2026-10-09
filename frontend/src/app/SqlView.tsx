import { useEffect, useMemo, useRef, useState } from 'react'

import { ResultsTable, columnNames, columnTypes } from '../core'
import { apiFetch } from './api'
import { Spinner } from './controls/Spinner'
import { flushPatches, patchView, viewState } from './session'
import { resultSummary, runnableText, type StatementResult } from './sqlScript'

// The Queries page (`/sql`), mounted by the App shell only for a ready
// connection: one flat SQL textbox whose `;`-separated statements run as
// written — writes and DDL included, no pagination, nothing saved — one
// result block per statement (docs/sql.md).
function SqlView({ runOn }: { runOn?: string | null }) {
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

  async function run() {
    const el = inputRef.current
    const text = el ? runnableText(sql, el.selectionStart, el.selectionEnd) : sql
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
      void run()
    }
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
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void run()}
            disabled={busy || !sql.trim()}
            data-testid="sql-run"
            className="glass-btn-primary px-4 py-2 font-medium"
          >
            Run
          </button>
          {busy && (
            <span data-testid="sql-busy" role="status" aria-label="Running">
              <Spinner />
            </span>
          )}
          <span className="text-xs text-slate-400">
            Separate statements with <code className="font-mono">;</code> — they run in order and
            stop at the first error. Select some text to run only that. Ctrl/⌘+Enter runs.
          </span>
        </div>
        {error && (
          <p data-testid="sql-error" className="text-sm text-red-300">
            {error}
          </p>
        )}
        {results !== null && (
          <div data-testid="sql-results" className="flex flex-col gap-3">
            {results.map((r, i) => (
              <StatementBlock key={i} result={r} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

// One statement's block: the statement, its summary line, and its rows when it
// returned any.
function StatementBlock({ result }: { result: StatementResult }) {
  const rows = useMemo(
    () => (result.meta && result.data ? { meta: result.meta, data: result.data } : null),
    [result],
  )
  const columns = useMemo(() => (rows ? columnNames(rows) : []), [rows])
  const types = useMemo(() => (rows ? columnTypes(rows) : {}), [rows])
  const shownIdx = useMemo(() => columns.map((_, i) => i), [columns])

  return (
    <div
      data-testid="sql-result"
      data-ok={result.ok}
      className={`flex flex-col gap-2 rounded-xl border p-3 ${
        result.ok ? 'border-white/10 bg-white/[0.02]' : 'border-red-400/40 bg-red-500/5'
      }`}
    >
      <pre
        data-testid="sql-result-sql"
        className="max-h-24 overflow-auto whitespace-pre-wrap font-mono text-xs text-slate-300"
      >
        {result.sql}
      </pre>
      {result.ok ? (
        <p data-testid="sql-result-status" className="text-xs text-slate-400">
          {resultSummary(result)}
        </p>
      ) : (
        <p data-testid="sql-result-error" className="text-sm text-red-300">
          {resultSummary(result)}
        </p>
      )}
      {rows && (
        <ResultsTable
          columns={columns}
          rows={rows.data}
          types={types}
          shownIdx={shownIdx}
          testid="sql-result-rows"
        />
      )}
    </div>
  )
}

export default SqlView
