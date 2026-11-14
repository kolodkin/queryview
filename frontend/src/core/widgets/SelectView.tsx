// `<qv-select-view query>`: a paged results table over one of the dashboard's
// queries, with field and order-by pickers and CSV. It never holds SQL: every
// run asks the host by query name. See docs/dashboard.md, "Widgets".

import { useCallback, useEffect, useRef, useState } from 'react'

import { renderCellTemplate } from '../cells/cellTemplate'
import { renderCell } from '../cells/cellViewYaml'
import type { WidgetReply } from '../dashboard/widgetChannel'
import { FieldPickers, type Field, type OrderCol } from '../presentation/FieldPickers'
import { shownColumnIndices } from '../presentation/presentation'
import { ResultsTable } from '../results/ResultsTable'
import { cellText, columnNames, columnTypes, type QueryRows } from '../results/rows'
import { onParamsResults, requestHost, tellHost } from './frameChannel'

type Page = { limit: number; offset: number; orderBy: OrderCol[] }

const inputClass = 'glass-input ml-1 w-20 px-2 py-1 text-sm'

export function SelectView({
  query,
  limit = 100,
  orderBy = [],
  fields: initialFields = [],
  templates = {},
}: {
  query: string
  limit?: number
  // The saved presentation; changes made here last for the visit.
  orderBy?: OrderCol[]
  fields?: string[]
  // Column name → the HTML of its <template column>.
  templates?: Record<string, string>
}) {
  const [page, setPage] = useState<Page>({ limit, offset: 0, orderBy })
  const [result, setResult] = useState<QueryRows | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [fields, setFields] = useState<Field[]>([])
  const [visibleCols, setVisibleCols] = useState<string[]>([])
  // Only the newest run lands: a slow reply must not overwrite a later page.
  const runSeq = useRef(0)
  const firstResult = useRef(true)

  const run = useCallback(
    async (p: Page) => {
      const ticket = ++runSeq.current
      setBusy(true)
      const reply = await requestHost<Extract<WidgetReply, { type: 'widget-result' }>>({
        type: 'widget-query',
        query,
        limit: p.limit,
        offset: p.offset,
        order_by: p.orderBy,
      })
      if (ticket !== runSeq.current) return
      setBusy(false)
      if (!reply.ok) {
        setError(reply.message)
        return
      }
      setError(null)
      const rows: QueryRows = { meta: reply.meta, data: reply.data }
      setResult(rows)
      // The `fields` attribute restricts the table to those columns at first.
      if (firstResult.current && initialFields.length) {
        const cols = columnNames(rows)
        setFields(cols.map((name) => ({ name, type: '' })))
        setVisibleCols(initialFields.filter((f) => cols.includes(f)))
      }
      firstResult.current = false
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [query],
  )

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void run(page)
  }, [run, page])

  // A param change or an edited query: back to the first page.
  useEffect(() => onParamsResults(() => setPage((p) => ({ ...p, offset: 0 }))), [])

  async function describe() {
    const reply = await requestHost<Extract<WidgetReply, { type: 'widget-fields' }>>({
      type: 'widget-describe',
      query,
    })
    if (!reply.ok) {
      setError(reply.message)
      return
    }
    setFields(reply.fields)
    setVisibleCols(reply.fields.map((f) => f.name))
  }

  const columns = result ? columnNames(result) : []
  const colTypes = result ? columnTypes(result) : {}

  return (
    <section
      data-testid="qv-select-view"
      className="flex max-h-[36rem] flex-col gap-2 rounded-xl bg-slate-950 p-3 text-sm text-slate-200"
    >
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void describe()}
          data-testid="qv-fields"
          className={`px-3 py-1 text-sm font-medium ${fields.length ? 'glass-btn-primary' : 'glass-btn'}`}
        >
          Fields
        </button>
        <label className="text-slate-300">
          Limit
          <input
            type="number"
            value={page.limit}
            min={1}
            max={1000}
            onChange={(e) =>
              setPage({ ...page, limit: Math.min(1000, Math.max(1, Number(e.target.value) || 1)) })
            }
            data-testid="qv-limit"
            className={inputClass}
          />
        </label>
        <label className="text-slate-300">
          Offset
          <input
            type="number"
            value={page.offset}
            min={0}
            onChange={(e) =>
              setPage({ ...page, offset: Math.max(0, Math.trunc(Number(e.target.value)) || 0) })
            }
            data-testid="qv-offset"
            className={inputClass}
          />
        </label>
        <button
          type="button"
          onClick={() => setPage({ ...page, offset: Math.max(0, page.offset - page.limit) })}
          disabled={busy || page.offset === 0}
          data-testid="qv-prev"
          className="glass-btn px-3 py-1"
        >
          ← Previous
        </button>
        <button
          type="button"
          onClick={() => setPage({ ...page, offset: page.offset + page.limit })}
          disabled={busy}
          data-testid="qv-next"
          className="glass-btn px-3 py-1"
        >
          Next →
        </button>
        <button
          type="button"
          onClick={() =>
            tellHost({
              type: 'widget-csv',
              query,
              limit: page.limit,
              offset: page.offset,
              order_by: page.orderBy,
            })
          }
          data-testid="qv-csv"
          className="glass-btn px-3 py-1 font-medium text-emerald-300"
        >
          Download CSV
        </button>
      </div>

      {fields.length > 0 && (
        <FieldPickers
          fields={fields}
          visibleCols={visibleCols}
          orderBy={page.orderBy}
          onVisibleColsChange={setVisibleCols}
          onOrderByChange={(next) => setPage({ ...page, orderBy: next })}
        />
      )}

      {error ? (
        <p data-testid="qv-error" className="text-red-300">
          {error}
        </p>
      ) : (
        result && (
          <ResultsTable
            columns={columns}
            types={colTypes}
            rows={result.data}
            shownIdx={shownColumnIndices(columns, fields, visibleCols)}
            testid="qv-results"
            dimmed={busy}
            renderCell={(col, value, row) =>
              templates[col] !== undefined ? (
                <span
                  data-testid={`cell-${col}`}
                  dangerouslySetInnerHTML={{
                    __html: renderCellTemplate(
                      templates[col],
                      cellText(value),
                      row.map(cellText),
                      columns,
                    ),
                  }}
                />
              ) : (
                renderCell(col, value, {}, row, columns, colTypes)
              )
            }
          />
        )
      )}
    </section>
  )
}
