// The results grid shared by the query panel and the explorer: a sticky-header
// table over result rows, restricted to the visible columns (see
// shownColumnIndices in presentation.ts). It fills the rest of its flex-column
// parent (at least 12rem) and scrolls inside, both ways.
//
// Each column is as wide as its header or widest value, up to a cap (see
// cellWidth.ts), so a short table fits on screen and one long-text column can't
// stretch the grid: a value that doesn't fit scrolls inside its own cell and
// gets a button, at the cell's left edge, opening it in CellDataModal. Widths
// come from the values' text, so a column whose cells a view draws wider than
// that (`capped`, or holding containers) keeps the cap.

import { useMemo, useState } from 'react'

import { CellDataModal } from '../cells/CellDataModal'
import { detectFormat } from '../cells/structured'
import { columnSize, columnsWidth, isOverflowing } from './cellWidth'
import { cellText, isContainer, type Cell } from './rows'

type Opened = { column: string; value: Cell; type?: string }

type RenderCell = (col: string, value: Cell, row: Cell[]) => React.ReactNode

function BodyCell({
  col,
  type,
  value,
  text,
  row,
  width,
  renderCell,
  onOpen,
}: {
  col: string
  type?: string
  value: Cell
  // cellText(value), measured once by the table for the column's width.
  text: string
  row: Cell[]
  width: string
  renderCell?: RenderCell
  onOpen: (opened: Opened) => void
}) {
  const overflowing = isOverflowing(text)
  // Detection only names the format for the glyph, so it is skipped for values
  // that fit and memoised so re-rendering doesn't re-parse.
  const format = useMemo(() => (isOverflowing(text) ? detectFormat(text) : null), [text])

  return (
    <td
      style={{ width }}
      className="border-b border-white/5 px-2 py-1 align-top font-mono text-slate-200"
    >
      <div className="flex items-start gap-1">
        {overflowing && (
          <button
            type="button"
            onClick={() => onOpen({ column: col, value, type })}
            data-testid="cell-expand"
            data-col={col}
            aria-label={`Open ${col} value`}
            title={format ? `Open parsed ${format}` : 'Open full value'}
            className="shrink-0 rounded px-1 text-xs leading-5 text-slate-400 hover:bg-white/10 hover:text-indigo-200"
          >
            {format ? '{ }' : '⤢'}
          </button>
        )}
        {/* The cell's own scroller, so long values never widen the column. */}
        <div className="cell-scroll min-w-0 flex-1 overflow-x-auto whitespace-pre">
          {renderCell ? renderCell(col, value, row) : text}
        </div>
      </div>
    </td>
  )
}

export function ResultsTable({
  columns,
  rows,
  shownIdx,
  testid,
  renderCell,
  capped,
  dimmed = false,
  types = {},
}: {
  columns: string[]
  rows: Cell[][]
  // Column name → database type, from the result's meta.
  types?: Record<string, string>
  shownIdx: number[]
  testid: string
  // Cell content; defaults to plain text (the query panel plugs in cell views).
  renderCell?: RenderCell
  // Columns renderCell draws wider than their text: they keep the cap.
  capped?: (col: string) => boolean
  // Faded while a re-run is in flight.
  dimmed?: boolean
}) {
  const [open, setOpen] = useState<Opened | null>(null)
  // Each shown column's cell texts and size, from the rows on screen: measured
  // once per result, not per cell or render.
  const { texts, sizes } = useMemo(() => {
    const texts = shownIdx.map((i) => rows.map((row) => cellText(row[i])))
    const sizes = shownIdx.map((i, n) =>
      columnSize(
        columns[i],
        texts[n],
        capped?.(columns[i]) || rows.some((row) => isContainer(row[i])),
      ),
    )
    return { texts, sizes }
  }, [columns, rows, shownIdx, capped])
  const widths = sizes.map((s) => columnsWidth([s]))
  const tableWidth = columnsWidth(sizes)

  return (
    <div
      data-testid={testid}
      className={`min-h-0 flex-[1_1_12rem] overflow-auto rounded-xl border border-white/10 ${
        dimmed ? 'opacity-50 transition-opacity' : ''
      }`}
    >
      {/* `table-layout: fixed` only takes effect on a table with an explicit
          width — left to `auto`, the browser falls back to automatic layout and
          long values stretch their column again. */}
      <table
        style={{ width: tableWidth }}
        className="table-fixed border-collapse text-left font-mono text-sm"
      >
        <thead className="sticky top-0 bg-[rgba(16,20,36,0.62)] backdrop-blur-lg">
          <tr>
            {shownIdx.map((i, n) => (
              <th
                key={i}
                style={{ width: widths[n] }}
                title={columns[i]}
                className="truncate border-b border-white/10 px-2 py-2 font-semibold text-slate-200"
              >
                {columns[i]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="odd:bg-transparent even:bg-white/[0.03]">
              {shownIdx.map((j, n) => (
                <BodyCell
                  key={j}
                  col={columns[j]}
                  type={types[columns[j]]}
                  value={row[j]}
                  text={texts[n][i]}
                  row={row}
                  width={widths[n]}
                  renderCell={renderCell}
                  onOpen={setOpen}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {open && (
        <CellDataModal
          column={open.column}
          value={open.value}
          type={open.type}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  )
}
