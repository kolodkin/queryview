import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  FieldPickers,
  ResultsTable,
  columnNames,
  shownColumnIndices,
  type Field,
  type OrderCol,
  type QueryRows,
} from '../core'
import { isReady, type Connection } from './connection'
import { formatBytes, formatCompact } from './compactNumber'

// Sidebar entry from /api/db/tables. rows/bytes are engine estimates — null
// when the engine doesn't track them (views, never-analyzed Postgres tables);
// query is the ready-to-run browse SELECT, quoted server-side with the
// driver's identifier quote.
type TableInfo = { name: string; rows: number | null; bytes: number | null; query: string }

// The "1.2K rows · 3.4MB" subline, or null when the engine knows neither.
function tableMeta(t: TableInfo): string | null {
  const parts = [
    t.rows != null ? `${formatCompact(t.rows)} rows` : null,
    t.bytes != null ? formatBytes(t.bytes) : null,
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : null
}

// The classical table-navigator page (`/explorer?table=x`): a sidebar lists the
// active database's tables; picking one browses its rows with the same field
// select / order-by select as the query panel. Field selection is client-side
// column visibility, order-by and pagination go to the server.
function ExplorerView({ connection }: { connection: Connection | null }) {
  const ready = isReady(connection)
  const database = connection?.database ?? null
  const [searchParams, setSearchParams] = useSearchParams()
  const table = searchParams.get('table') ?? ''

  const [tables, setTables] = useState<TableInfo[]>([])
  const [tablesError, setTablesError] = useState<string | null>(null)
  const [fields, setFields] = useState<Field[]>([])
  const [visibleCols, setVisibleCols] = useState<string[]>([])
  const [orderBy, setOrderBy] = useState<OrderCol[]>([])
  const [limit, setLimit] = useState(100)
  const [offset, setOffset] = useState(0)
  const [result, setResult] = useState<QueryRows | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // The limit the current output was fetched with, so a no-op blur of the
  // Limit input doesn't refetch the page.
  const appliedLimit = useRef(100)
  // Browse runs overlap — adding an order-by column and flipping its direction
  // fire back to back, and paging follows a limit change — and the server
  // answers them concurrently. Each run takes a ticket so only the newest may
  // write the output; otherwise a slower earlier query's rows land last and the
  // table contradicts the controls until something else re-runs it.
  const runSeq = useRef(0)

  // The sidebar entry the URL selects, once the list has it. Row loading keys
  // off this: nothing fires until the table is confirmed present, so a stale
  // selection (e.g. after a database switch) never issues doomed queries.
  const selected = tables.find((t) => t.name === table)

  // Load the sidebar whenever the active database changes; a selected table
  // that vanished (database switch) is dropped from the URL.
  useEffect(() => {
    if (!ready) return
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch('/api/db/tables')
        const data = await res.json()
        if (cancelled) return
        if (data.ok) {
          const list = (data.tables ?? []) as TableInfo[]
          setTables(list)
          setTablesError(null)
          if (table && !list.some((t) => t.name === table)) {
            setSearchParams({}, { replace: true })
          }
        } else {
          setTables([])
          setTablesError((data.message as string) ?? 'failed to list tables')
        }
      } catch (err) {
        if (!cancelled) {
          setTables([])
          setTablesError(err instanceof Error ? err.message : 'request failed')
        }
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, database])

  const runQuery = useCallback(
    async (sql: string, lim: number, off: number, ord: OrderCol[]) => {
      const ticket = ++runSeq.current
      setBusy(true)
      setError(null)
      try {
        const res = await fetch('/api/db/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: sql,
            limit: lim,
            offset: off,
            order_by: ord,
          }),
        })
        const data = await res.json()
        if (ticket !== runSeq.current) return
        if (data.ok) {
          setResult({ meta: data.meta ?? [], data: data.data ?? [] })
          setOffset(off)
          appliedLimit.current = lim
        } else {
          setError((data.message as string) ?? 'query failed')
        }
      } catch (err) {
        if (ticket !== runSeq.current) return
        setError(err instanceof Error ? err.message : 'request failed')
      } finally {
        if (ticket === runSeq.current) setBusy(false)
      }
    },
    [],
  )

  // A confirmed selection (also after a database switch reloads the list):
  // reset the presentation, then describe and load the first page — the two
  // requests are independent, so they run concurrently.
  useEffect(() => {
    if (!ready || !selected) return
    const sql = selected.query
    let cancelled = false
    /* eslint-disable react-hooks/set-state-in-effect */
    setResult(null)
    setError(null)
    setFields([])
    setVisibleCols([])
    setOrderBy([])
    setOffset(0)
    /* eslint-enable react-hooks/set-state-in-effect */
    void (async () => {
      try {
        const res = await fetch('/api/db/describe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: sql }),
        })
        const data = await res.json()
        if (!cancelled && data.ok) {
          const next = (data.fields ?? []) as Field[]
          setFields(next)
          setVisibleCols(next.map((f) => f.name))
        }
        // A failed describe isn't fatal: the run reports the real error.
      } catch {
        /* ditto */
      }
    })()
    void runQuery(sql, limit, 0, [])
    return () => {
      cancelled = true
    }
    // limit is intentionally not a dependency: changing it re-runs via its own
    // handler; it must not reset the field/order selections. `tables` (via
    // `selected`) is: a database switch refreshes the list and reloads the rows.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, selected, runQuery])

  // Order-by changes re-run immediately — browsing wants instant feedback, and
  // the query is the cheap paginated SELECT the server already ran.
  function changeOrder(next: OrderCol[]) {
    setOrderBy(next)
    if (selected) void runQuery(selected.query, limit, offset, next)
  }

  function page(nextOffset: number) {
    if (selected) void runQuery(selected.query, limit, Math.max(0, nextOffset), orderBy)
  }

  const { columns, rows } = useMemo(
    () => (result ? { columns: columnNames(result), rows: result.data } : { columns: [], rows: [] }),
    [result],
  )
  const shownIdx = useMemo(
    () => shownColumnIndices(columns, fields, visibleCols),
    [columns, fields, visibleCols],
  )

  if (!ready) {
    return (
      <div className="w-full max-w-md text-center">
        <h1 className="text-3xl font-bold tracking-tight text-white [text-shadow:0_2px_30px_rgba(129,140,248,0.45)]">
          Explorer
        </h1>
        <p data-testid="explorer-hint" className="mt-4 text-sm text-slate-400">
          Connect and select a database on the Queries page first.
        </p>
      </div>
    )
  }

  return (
    // mt-10 keeps the panels clear of the absolutely-positioned connection
    // pill (top-left) and nav (top-right) when the content is viewport-tall.
    <div className="mt-10 flex w-full max-w-[85vw] items-start gap-4">
      <aside data-testid="explorer-tables" className="glass-panel w-64 shrink-0 p-4">
        <h2 className="text-sm font-semibold text-slate-200">Tables</h2>
        {tablesError && (
          <p data-testid="explorer-tables-error" className="mt-2 text-sm text-red-300">
            {tablesError}
          </p>
        )}
        <div className="mt-2 max-h-[70vh] space-y-1 overflow-auto">
          {tables.map((t) => {
            const meta = tableMeta(t)
            return (
              <button
                key={t.name}
                type="button"
                data-testid="explorer-table"
                data-table={t.name}
                onClick={() => setSearchParams({ table: t.name })}
                className={`flex w-full items-baseline gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-white/10 ${
                  t.name === table
                    ? 'bg-white/10 font-medium text-indigo-200'
                    : 'text-slate-200'
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{t.name}</span>
                {meta && (
                  <span
                    data-testid="explorer-table-meta"
                    className="shrink-0 whitespace-nowrap text-xs font-normal text-slate-400"
                  >
                    {meta}
                  </span>
                )}
              </button>
            )
          })}
          {tables.length === 0 && !tablesError && (
            <p className="text-sm text-slate-400">No tables.</p>
          )}
        </div>
      </aside>

      <section data-testid="explorer-panel" className="glass-panel min-w-0 flex-1 space-y-3 p-6">
        {!table ? (
          <p data-testid="explorer-hint" className="text-sm text-slate-400">
            Select a table to browse its rows.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <h2
                data-testid="explorer-table-name"
                className="mr-auto truncate text-lg font-semibold text-white"
              >
                {table}
              </h2>
              <label className="text-sm text-slate-300">
                Limit
                <input
                  type="number"
                  value={limit}
                  min={1}
                  onChange={(e) => setLimit(Number(e.target.value) || 1)}
                  onBlur={() => {
                    if (limit !== appliedLimit.current) page(0)
                  }}
                  aria-label="Limit"
                  data-testid="explorer-limit"
                  className="glass-input ml-1 w-20 px-3 py-2"
                />
              </label>
              <button
                type="button"
                onClick={() => page(offset - limit)}
                disabled={busy || offset === 0}
                data-testid="explorer-prev"
                className="glass-btn px-3 py-2 text-sm"
              >
                ← Previous
              </button>
              <button
                type="button"
                onClick={() => page(offset + limit)}
                disabled={busy}
                data-testid="explorer-next"
                className="glass-btn px-3 py-2 text-sm"
              >
                Next →
              </button>
              <span data-testid="explorer-offset" className="text-xs text-slate-400">
                offset {offset}
              </span>
            </div>

            {fields.length > 0 && (
              <FieldPickers
                fields={fields}
                visibleCols={visibleCols}
                orderBy={orderBy}
                onVisibleColsChange={setVisibleCols}
                onOrderByChange={changeOrder}
                orderHeaderExtra={
                  <span className="text-xs text-slate-400">(re-runs the query)</span>
                }
              />
            )}

            {result !== null && (
              <ResultsTable
                columns={columns}
                rows={rows}
                shownIdx={shownIdx}
                testid="explorer-output"
              />
            )}
            {error && (
              <p data-testid="explorer-error" className="text-sm text-red-300">
                {error}
              </p>
            )}
          </>
        )}
      </section>
    </div>
  )
}

export default ExplorerView
