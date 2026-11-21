import { useState, type Ref } from 'react'

import { DashboardFrame, useDismiss } from '../core'
import { useEditLock } from './sessionLock'
import { queryViewHtml } from './widgetHost'
import TextareaSizes from './controls/TextareaSizes'
import { textareaSizeClass } from './textareaSizes'

const NO_RESULTS = {}

// The dashboard's query popup: pick one of its queries, edit the SQL, and see
// its rows. It sits in the app, outside the dashboard's sandboxed frame: that
// frame's widgets only ever name a query, so SQL is typed here alone. The rows
// are a `<qv-select-view>` in a frame of the popup's own, answered by the
// dashboard page like any widget. Focus inside holds the human edit lock,
// like the Scripts page.
function DashboardSqlPanel({
  queries,
  onChange,
  onExecute,
  onClose,
  remoteId,
  frameRef,
  loadSeq,
}: {
  queries: Record<string, string>
  onChange: (name: string, sql: string) => void
  onExecute: () => void
  onClose: () => void
  remoteId: string | null
  // The results frame: the host answers its widget like the dashboard's own.
  frameRef: Ref<HTMLIFrameElement>
  // Bumped per dashboard load (a database switch): the results reload with it.
  loadSeq: number
}) {
  const names = Object.keys(queries)
  const [picked, setPicked] = useState(names[0] ?? '')
  const [rows, setRows] = useState(8)
  // A press on the backdrop, or Escape, closes; edits are kept.
  const panelRef = useDismiss<HTMLDivElement>(true, onClose)
  useEditLock(panelRef, remoteId)
  // The picked query may be gone after another dashboard loads.
  const name = names.includes(picked) ? picked : (names[0] ?? '')

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Dashboard queries"
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-6 backdrop-blur-sm"
    >
      <div
        ref={panelRef}
        data-testid="dash-sql-panel"
        className="glass-popover flex max-h-[90vh] w-full max-w-6xl flex-col gap-3 overflow-auto p-5"
      >
        <div className="flex items-center gap-2">
          <select
            data-testid="dash-sql-query"
            aria-label="Query"
            value={name}
            onChange={(e) => setPicked(e.target.value)}
            className="glass-input min-w-40 px-3 py-1 text-sm"
          >
            {names.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <TextareaSizes
            rows={rows}
            onChange={setRows}
            testid="dash-sql-size"
            className="ml-auto flex items-center gap-1"
          />
          <button
            type="button"
            onClick={onClose}
            data-testid="dash-sql-close"
            className="glass-btn px-3 py-1 text-xs"
          >
            Close
          </button>
        </div>
        <textarea
          value={queries[name] ?? ''}
          onChange={(e) => onChange(name, e.target.value)}
          disabled={!name}
          aria-label="SQL"
          data-testid="dash-sql"
          rows={rows || 1}
          spellCheck={false}
          placeholder="SELECT …"
          className={`glass-input w-full px-3 font-mono text-sm ${textareaSizeClass(rows)}`}
        />
        <div>
          <button
            type="button"
            onClick={onExecute}
            disabled={!name}
            data-testid="dash-sql-execute"
            className="glass-btn-primary px-4 py-2 font-medium"
          >
            Execute
          </button>
        </div>
        {name && (
          <DashboardFrame
            key={`${loadSeq}:${name}`}
            ref={frameRef}
            testid="dash-sql-frame"
            html={queryViewHtml(name)}
            results={NO_RESULTS}
            className="h-[45vh] w-full shrink-0 rounded-xl border border-white/10"
          />
        )}
      </div>
    </div>
  )
}

export default DashboardSqlPanel
