import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ResultsTable, columnNames, columnTypes, type QueryRows } from '../core'
import { apiFetch } from './api'
import { Spinner } from './controls/Spinner'
import { loadIntoQueryView } from './queryPanel'
import { flushPatches, patchView, viewState } from './session'
import { useEditLock } from './sessionLock'
import { failedSpan, runSummary, statementRangeAt, type Span, type StatementResult } from './script'
import { TEXTAREA_SIZES, textareaSizeClass } from './textareaSizes'

// A script the agent pushed (MCP push_script).
export type ScriptPush = { sql: string; run: boolean }

type ScriptsViewProps = {
  pushed: ScriptPush | null
  onPushConsumed: () => void
  remoteId: string | null
}

// The Scripts page (`/scripts`, docs/scripts.md), mounted by the App shell only
// for a ready connection: a flat SQL textbox whose statements run as written.
// Run takes the statement under the cursor (or the selection), Run all the
// whole script; a run leaves one status line and the last statement's rows.
function ScriptsView({ pushed, onPushConsumed, remoteId }: ScriptsViewProps) {
  const navigate = useNavigate()
  // The text is restored from the session; results never are (docs/session.md).
  const [sql, setSql] = useState(() => {
    // 'queries' is the pre-rename key, read so existing sessions keep their text.
    const saved = viewState('scripts').sql ?? viewState('queries').sql
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
  // Focus in the panel holds the edit lock (a push can't clobber typing);
  // leaving it writes the text to the session.
  const panelRef = useRef<HTMLElement>(null)
  useEditLock(panelRef, remoteId)

  function edit(next: string) {
    setSql(next)
    // Queued for the session; the write lands when the textbox is left.
    patchView('scripts', { sql: next })
  }

  // The selection when there is one, else the statement under the cursor.
  function currentStatement(): Span {
    const el = inputRef.current!
    if (sql.slice(el.selectionStart, el.selectionEnd).trim()) {
      return { start: el.selectionStart, end: el.selectionEnd }
    }
    return statementRangeAt(sql, el.selectionStart) ?? { start: 0, end: 0 }
  }

  // Runs the [start, end) slice of `script` (the textbox, unless a push's text
  // hasn't reached state yet).
  async function run({ start, end }: Span, script = sql) {
    const text = script.slice(start, end)
    // No busy guard here: a push must run even mid-run (runSeq drops the stale
    // result); the buttons and shortcut guard the user's own double runs.
    if (!text.trim()) return
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
        setFailed(span && { script, span })
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

  // Apply a push once: load the text (saved to the session like an edit), then
  // run it all when asked. The ref keeps StrictMode's double mount effect from
  // running a script (writes included) twice.
  const appliedPush = useRef<ScriptPush | null>(null)
  useEffect(() => {
    if (!pushed || appliedPush.current === pushed) return
    appliedPush.current = pushed
    edit(pushed.sql)
    void flushPatches()
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (pushed.run) void run({ start: 0, end: pushed.sql.length }, pushed.sql)
    onPushConsumed()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pushed])

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      if (busy) return
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
          testid="scripts-output"
          dimmed={busy}
        />
      ),
    [lastRows, busy],
  )
  const mark = failed && failed.script === sql && rows > 0 ? failed.span : null

  return (
    <div data-testid="scripts-page" className="viewport-page flex w-full max-w-[80vw] flex-col">
      <div className="mb-6 flex items-center justify-center">
        <h1 className="text-3xl font-bold tracking-tight text-white [text-shadow:0_2px_30px_rgba(129,140,248,0.45)]">
          Scripts
        </h1>
      </div>
      <section ref={panelRef} className="glass-panel flex grow flex-col gap-3 p-6">
        <div className="flex items-center justify-end gap-1">
          {TEXTAREA_SIZES.map(([label, n]) => (
            <button
              key={label}
              type="button"
              onClick={() => setRows(n)}
              data-testid={`scripts-size-${label.toLowerCase()}`}
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
            onScroll={(e) => {
              if (markRef.current) markRef.current.scrollTop = e.currentTarget.scrollTop
            }}
            aria-label="SQL script"
            data-testid="scripts-input"
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
              <mark data-testid="scripts-failed-mark" className="rounded bg-red-500/15 text-red-300">
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
            data-testid="scripts-run-current"
            title="Run the statement under the cursor, or the selection (Ctrl/⌘+Enter)"
            className="glass-btn-primary px-4 py-2 font-semibold"
          >
            ▶ Run
          </button>
          <button
            type="button"
            onClick={() => void run({ start: 0, end: sql.length })}
            disabled={busy || !sql.trim()}
            data-testid="scripts-run-all"
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
            data-testid="scripts-open-queryview"
            title="Load the last statement's SQL into QueryView for paging, saving and presentation"
            className="glass-btn px-3 py-2 text-sm font-medium"
          >
            Open in QueryView
          </button>
          {busy && (
            <span data-testid="scripts-busy" role="status" aria-label="Running">
              <Spinner />
            </span>
          )}
          <span className="text-xs text-slate-400">
            Separate statements with <code className="font-mono">;</code>. Run all stops at the
            first error.
          </span>
        </div>
        {error && (
          <p data-testid="scripts-error" className="text-sm text-red-300">
            {error}
          </p>
        )}
        {results !== null && (
          <p
            data-testid="scripts-status"
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

export default ScriptsView
