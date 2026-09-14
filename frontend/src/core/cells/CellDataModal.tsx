// The cell popup: the full value of a result cell too long to read in the grid
// (see ResultsTable). Text that parses as JSON or YAML opens on a collapsible
// parsed tree with a Raw toggle; anything else is just the wrapped raw text.
// Distinct from CellViewModal, which edits a query's cell_view config.

import { useMemo, useState } from 'react'

import { detectStructured } from './structured'
import { ROOT_PATH, defaultCollapsed, treeRows } from './structuredTree'

function ParsedTree({ data }: { data: unknown }) {
  const [collapsed, setCollapsed] = useState(() => defaultCollapsed(data))
  const rows = useMemo(() => treeRows(data, collapsed), [data, collapsed])

  function toggle(path: string) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (!next.delete(path)) next.add(path)
      return next
    })
  }

  return (
    <div data-testid="cell-data-tree" className="font-mono text-xs leading-relaxed">
      {rows.map((r) => (
        <div
          key={r.path}
          data-testid="cell-data-row"
          className="flex items-baseline gap-1 whitespace-pre-wrap break-all"
          style={{ paddingLeft: `${r.depth}rem` }}
        >
          {r.expandable ? (
            <button
              type="button"
              onClick={() => toggle(r.path)}
              data-testid="cell-data-toggle"
              aria-expanded={!collapsed.has(r.path)}
              className="w-3 shrink-0 text-slate-400 hover:text-slate-200"
            >
              {collapsed.has(r.path) ? '▸' : '▾'}
            </button>
          ) : (
            <span className="w-3 shrink-0" />
          )}
          {r.key !== null && <span className="text-indigo-300">{r.key}:</span>}
          {r.key === null && r.path === ROOT_PATH && <span className="text-slate-500">root</span>}
          <span className="text-slate-200">{r.summary}</span>
        </div>
      ))}
    </div>
  )
}

export function CellDataModal({
  column,
  text,
  onClose,
}: {
  column: string
  text: string
  onClose: () => void
}) {
  const structured = useMemo(() => detectStructured(text), [text])
  const [raw, setRaw] = useState(false)
  const showParsed = structured !== null && !raw

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Cell value: ${column}`}
      data-testid="cell-data-modal"
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-6 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="glass-popover flex max-h-[80vh] w-full max-w-3xl flex-col p-5">
        <div className="mb-3 flex items-center gap-3">
          <h3 className="min-w-0 flex-1 truncate text-base font-semibold text-slate-100">
            {column}
          </h3>
          {structured && (
            <span
              data-testid="cell-data-format"
              className="glass-chip px-2 py-0.5 text-xs uppercase"
            >
              {structured.format}
            </span>
          )}
          {structured && (
            <button
              type="button"
              onClick={() => setRaw((r) => !r)}
              data-testid="cell-data-raw-toggle"
              className="glass-btn px-3 py-1 text-xs"
            >
              {raw ? 'Parsed' : 'Raw'}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            data-testid="cell-data-close"
            className="glass-btn px-3 py-1 text-xs"
          >
            Close
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-white/10 bg-black/20 p-3">
          {showParsed ? (
            <ParsedTree data={structured.data} />
          ) : (
            <pre
              data-testid="cell-data-raw"
              className="whitespace-pre-wrap break-all font-mono text-xs text-slate-200"
            >
              {text}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}
