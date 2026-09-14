// The results grid shared by the query panel and the explorer: a sticky-header
// table over result rows, restricted to the visible columns (see
// shownColumnIndices in presentation.ts).
//
// Columns are a fixed CELL_WIDTH_CH wide so one long-text column can't stretch
// the grid: a longer value scrolls inside its own cell and gets a button, at the
// cell's left edge, opening it in CellDataModal.

import { useMemo, useState } from 'react'

import { CellDataModal } from '../cells/CellDataModal'
import { CELL_WIDTH_CH, detectStructured, isOverflowing } from '../cells/structured'
import { cellText, type Cell } from './rows'

// The column box: CELL_WIDTH_CH characters of content plus the cells' own
// px-2 padding on both sides, so exactly that many characters are visible.
// The table is monospace throughout, so `ch` means the same in every cell.
const CELL_WIDTH = `calc(${CELL_WIDTH_CH}ch + 1rem)`

// `table-layout: fixed` only takes effect on a table with an explicit width —
// left to `auto`, the browser falls back to automatic layout and long values
// stretch their column again. So the table is sized to its own columns and the
// wrapper scrolls.
const tableWidth = (cols: number) => `calc(${cols} * (${CELL_WIDTH_CH}ch + 1rem))`

function BodyCell({
  col,
  value,
  children,
  onOpen,
}: {
  col: string
  value: Cell
  children: React.ReactNode
  onOpen: (column: string, text: string) => void
}) {
  const text = cellText(value)
  // Detection only decides the glyph, so it is skipped for values that fit and
  // memoised so re-rendering doesn't re-parse.
  const overflowing = isOverflowing(text)
  const structured = useMemo(
    () => (overflowing ? detectStructured(text) : null),
    [overflowing, text],
  )

  return (
    <td
      style={{ width: CELL_WIDTH }}
      className="border-b border-white/5 px-2 py-1 align-top font-mono text-slate-200"
    >
      <div className="flex items-start gap-1">
        {overflowing && (
          <button
            type="button"
            onClick={() => onOpen(col, text)}
            data-testid="cell-expand"
            data-col={col}
            aria-label={`Open ${col} value`}
            title={structured ? `Open parsed ${structured.format}` : 'Open full value'}
            className="shrink-0 rounded px-1 text-xs leading-5 text-slate-400 hover:bg-white/10 hover:text-indigo-200"
          >
            {structured ? '{ }' : '⤢'}
          </button>
        )}
        {/* The cell's own scroller, so long values never widen the column. */}
        <div className="cell-scroll min-w-0 flex-1 overflow-x-auto whitespace-pre">{children}</div>
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
}: {
  columns: string[]
  rows: Cell[][]
  shownIdx: number[]
  testid: string
  // Cell content; defaults to plain text (the query panel plugs in cell views).
  renderCell?: (col: string, value: Cell, row: Cell[]) => React.ReactNode
}) {
  const [open, setOpen] = useState<{ column: string; text: string } | null>(null)

  return (
    <div
      data-testid={testid}
      className="max-h-[70vh] overflow-auto rounded-xl border border-white/10"
    >
      <table
        style={{ width: tableWidth(shownIdx.length) }}
        className="table-fixed border-collapse text-left font-mono text-sm"
      >
        <thead className="sticky top-0 bg-[rgba(16,20,36,0.62)] backdrop-blur-lg">
          <tr>
            {shownIdx.map((i) => (
              <th
                key={i}
                style={{ width: CELL_WIDTH }}
                title={columns[i]}
                className="truncate border-b border-white/10 px-2 py-2 font-mono font-semibold text-slate-200"
              >
                {columns[i]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="odd:bg-transparent even:bg-white/[0.03]">
              {shownIdx.map((j) => (
                <BodyCell key={j} col={columns[j]} value={row[j]} onOpen={(c, t) => setOpen({ column: c, text: t })}>
                  {renderCell ? renderCell(columns[j], row[j], row) : cellText(row[j])}
                </BodyCell>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {open && (
        <CellDataModal column={open.column} text={open.text} onClose={() => setOpen(null)} />
      )}
    </div>
  )
}
