import { useRef, useState } from 'react'

import { useEditLock } from './sessionLock'
import TextareaSizes from './controls/TextareaSizes'
import { textareaSizeClass } from './textareaSizes'

// The dashboard's SQL editor. It sits in the app, outside the sandboxed frame:
// the frame's widgets only ever name a query, so SQL is typed here alone.
// Focus inside it holds the human edit lock, like the Scripts page.
function DashboardSqlPanel({
  queries,
  onChange,
  onExecute,
  remoteId,
}: {
  queries: Record<string, string>
  onChange: (name: string, sql: string) => void
  onExecute: () => void
  remoteId: string | null
}) {
  const names = Object.keys(queries)
  const [picked, setPicked] = useState(names[0] ?? '')
  const [rows, setRows] = useState(8)
  const panelRef = useRef<HTMLElement>(null)
  useEditLock(panelRef, remoteId)
  // The picked query may be gone after another dashboard loads.
  const name = names.includes(picked) ? picked : (names[0] ?? '')

  return (
    <section
      ref={panelRef}
      data-testid="dash-sql-panel"
      className="glass-panel mb-4 flex flex-col gap-3 p-4"
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
    </section>
  )
}

export default DashboardSqlPanel
