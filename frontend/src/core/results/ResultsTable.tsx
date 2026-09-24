// The results grid shared by the query panel and the explorer: a sticky-header
// table over result rows, restricted to the visible columns (see
// shownColumnIndices in presentation.ts).
//
// Columns are a fixed width (see cellWidth.ts) so one long-text column can't
// stretch the grid: a value that doesn't fit scrolls inside its own cell and
// gets a button, at the cell's left edge, opening it in CellDataModal.

import { useMemo, useState } from 'react'

import { CellDataModal } from '../cells/CellDataModal'
import { detectFormat } from '../cells/structured'
import { CELL_WIDTH, isOverflowing } from './cellWidth'
import { cellText, type Cell } from './rows'

type Opened = { column: string; text: string }

type RenderCell = (col: string, value: Cell, row: Cell[]) => React.ReactNode

function BodyCell({
  col,
  value,
  row,
  renderCell,
  onOpen,
}: {
  col: string
  value: Cell
  row: Cell[]
  renderCell?: RenderCell
  onOpen: (opened: Opened) => void
}) {
  const text = cellText(value)
  const overflowing = isOverflowing(text)
  // Detection only names the format for the glyph, so it is skipped for values
  // that fit and memoised so re-rendering doesn't re-parse.
  const format = useMemo(() => (isOverflowing(text) ? detectFormat(text) : null), [text])

  return (
    <td
      style={{ width: CELL_WIDTH }}
      className="border-b border-white/5 px-2 py-1 align-top font-mono text-slate-200"
    >
      <div className="flex items-start gap-1">
        {overflowing && (
          <button
            type="button"
            onClick={() => onOpen({ column: col, text })}
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
  className = 'max-h-[70vh]',
}: {
  columns: string[]
  rows: Cell[][]
  shownIdx: number[]
  testid: string
  // Cell content; defaults to plain text (the query panel plugs in cell views).
  renderCell?: RenderCell
  // Sizing of the scroll box; the explorer makes it fill its panel instead.
  className?: string
}) {
  const [open, setOpen] = useState<Opened | null>(null)

  return (
    <div
      data-testid={testid}
      className={`${className} overflow-auto rounded-xl border border-white/10`}
    >
      {/* `table-layout: fixed` only takes effect on a table with an explicit
          width — left to `auto`, the browser falls back to automatic layout and
          long values stretch their column again. */}
      <table
        style={{ width: `calc(${shownIdx.length} * ${CELL_WIDTH})` }}
        className="table-fixed border-collapse text-left font-mono text-sm"
      >
        <thead className="sticky top-0 bg-[rgba(16,20,36,0.62)] backdrop-blur-lg">
          <tr>
            {shownIdx.map((i) => (
              <th
                key={i}
                style={{ width: CELL_WIDTH }}
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
              {shownIdx.map((j) => (
                <BodyCell
                  key={j}
                  col={columns[j]}
                  value={row[j]}
                  row={row}
                  renderCell={renderCell}
                  onOpen={setOpen}
                />
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
