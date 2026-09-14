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
import { Loading, Spinner } from './controls/Spinner'
import {
  DEFAULT_SIDEBAR_WIDTH,
  MAX_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  clampSidebarWidth,
  loadSidebarWidth,
  saveSidebarWidth,
} from './explorerSettings'

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
  const [tablesLoading, setTablesLoading] = useState(false)
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
  // Sidebar width, dragged on its right edge and remembered across reloads so
  // long table names stay readable.
  const [sidebarWidth, setSidebarWidth] = useState(loadSidebarWidth)
  const [dragging, setDragging] = useState(false)
  const asideRef = useRef<HTMLElement | null>(null)
  // Captured on grab: the panel's left edge (fixed — widening the row's first
  // item can't move it) and the pointer's offset from its right edge, so the
  // panel doesn't jump when the handle is grabbed off-centre. dragWidth is
  // where the drag has got to, committed to state on release.
  const dragLeft = useRef(0)
  const dragOffset = useRef(0)
  const dragWidth = useRef(0)

  // The sidebar entry the URL selects, once the list has it. Row loading keys
  // off this: nothing fires until the table is confirmed present, so a stale
  // selection (e.g. after a database switch) never issues doomed queries.
  const selected = tables.find((t) => t.name === table)

  // Load the sidebar whenever the active database changes; a selected table
  // that vanished (database switch) is dropped from the URL.
  useEffect(() => {
    if (!ready) return
    let cancelled = false
    setTablesLoading(true) // eslint-disable-line react-hooks/set-state-in-effect
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
      } finally {
        if (!cancelled) setTablesLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, database])

  const runQuery = useCallback(
    async (sql: string, lim: number, off: number, ord: OrderCol[]) => {
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
        if (data.ok) {
          setResult({ meta: data.meta ?? [], data: data.data ?? [] })
          setOffset(off)
          appliedLimit.current = lim
        } else {
          setError((data.message as string) ?? 'query failed')
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'request failed')
      } finally {
        setBusy(false)
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

  // Edge drag. Each move paints the width straight onto the panel rather than
  // going through state, which would rebuild the results table (100+ rows) and
  // the table list every frame; state and the storage write happen once, on
  // release. Listeners are on the window so a drag outrunning the handle keeps
  // resizing.
  useEffect(() => {
    if (!dragging) return
    function onMove(e: PointerEvent) {
      const next = clampSidebarWidth(e.clientX - dragOffset.current - dragLeft.current)
      dragWidth.current = next
      if (asideRef.current) asideRef.current.style.width = `${next}px`
    }
    function onUp() {
      setDragging(false)
      resize(dragWidth.current)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }
  }, [dragging])

  // Every route to a new width (drag release, arrow keys, reset) lands here, so
  // all of them persist.
  function resize(width: number) {
    const next = clampSidebarWidth(width)
    setSidebarWidth(next)
    saveSidebarWidth(next)
  }

  // So the handle works without a pointer.
  function onHandleKeyDown(e: React.KeyboardEvent) {
    const step = e.shiftKey ? 48 : 16
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      resize(sidebarWidth - step)
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      resize(sidebarWidth + step)
    } else if (e.key === 'Home') {
      e.preventDefault()
      resize(DEFAULT_SIDEBAR_WIDTH)
    }
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
      <aside
        ref={asideRef}
        data-testid="explorer-tables"
        data-width={sidebarWidth}
        style={{ width: sidebarWidth }}
        className="glass-panel relative shrink-0 p-4"
      >
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-200">Tables</h2>
          {sidebarWidth !== DEFAULT_SIDEBAR_WIDTH && (
            <button
              type="button"
              data-testid="explorer-sidebar-reset"
              onClick={() => resize(DEFAULT_SIDEBAR_WIDTH)}
              title="Reset the sidebar width"
              className="glass-btn ml-auto px-1.5 py-0.5 text-xs text-slate-300"
            >
              Reset width
            </button>
          )}
        </div>
        {tablesError && (
          <p data-testid="explorer-tables-error" className="mt-2 text-sm text-red-300">
            {tablesError}
          </p>
        )}
        {tablesLoading ? (
          <Loading label="Loading tables…" testid="explorer-tables-loading" />
        ) : (
          <div className="mt-2 max-h-[70vh] space-y-1 overflow-auto">
            {tables.map((t) => {
              const meta = tableMeta(t)
              return (
                <button
                  key={t.name}
                  type="button"
                  data-testid="explorer-table"
                  data-table={t.name}
                  title={t.name}
                  onClick={() => setSearchParams({ table: t.name })}
                  className={`block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-white/10 ${
                    t.name === table
                      ? 'bg-white/10 font-medium text-indigo-200'
                      : 'text-slate-200'
                  }`}
                >
                  <span className="block truncate">{t.name}</span>
                  {meta && (
                    <span
                      data-testid="explorer-table-meta"
                      className="block truncate text-xs font-normal text-slate-400"
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
        )}
        <div
          data-testid="explorer-sidebar-resize"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the tables sidebar"
          aria-valuenow={sidebarWidth}
          aria-valuemin={MIN_SIDEBAR_WIDTH}
          aria-valuemax={MAX_SIDEBAR_WIDTH}
          tabIndex={0}
          onPointerDown={(e) => {
            e.preventDefault()
            const rect = asideRef.current?.getBoundingClientRect()
            dragLeft.current = rect?.left ?? 0
            dragOffset.current = e.clientX - (rect?.right ?? e.clientX)
            dragWidth.current = sidebarWidth
            setDragging(true)
          }}
          onDoubleClick={() => resize(DEFAULT_SIDEBAR_WIDTH)}
          onKeyDown={onHandleKeyDown}
          title="Drag to resize · double-click to reset"
          className={`absolute -right-1 top-0 h-full w-2 cursor-col-resize rounded-full transition ${
            dragging ? 'bg-indigo-400/70' : 'bg-transparent hover:bg-indigo-400/40'
          } focus:outline-none focus-visible:bg-indigo-400/70`}
        />
      </aside>

      <section data-testid="explorer-panel" className="glass-panel min-w-0 flex-1 space-y-3 p-6">
        {!table ? (
          <p data-testid="explorer-hint" className="text-sm text-slate-400">
            Select a table to browse its rows.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {/* flex-1 + min-w-0 truncates a long name rather than wrapping
                  the pagination controls onto a second row. */}
              <h2
                data-testid="explorer-table-name"
                title={table}
                className="min-w-0 flex-1 truncate text-lg font-semibold text-white"
              >
                {table}
              </h2>
              {busy && result !== null && (
                <span data-testid="explorer-busy" role="status" aria-label="Loading rows">
                  <Spinner />
                </span>
              )}
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

            {result === null && busy && (
              <Loading label="Loading rows…" testid="explorer-rows-loading" />
            )}
            {result !== null && (
              <div className={busy ? 'opacity-50 transition-opacity' : undefined}>
                <ResultsTable
                  columns={columns}
                  rows={rows}
                  shownIdx={shownIdx}
                  testid="explorer-output"
                />
              </div>
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
