// The header's Query timeout chip (docs/queryview.md): the seconds one request
// to the database may take, applied on blur or Enter and remembered with the
// session.

import { useState } from 'react'
import { loadQueryTimeout, parseQueryTimeout, saveQueryTimeout } from './queryTimeout'

export function QueryTimeoutChip() {
  const [timeout, setTimeout] = useState(loadQueryTimeout)
  const [draft, setDraft] = useState(String(timeout))

  async function apply() {
    const typed = parseQueryTimeout(draft)
    if (typed === null) return setDraft(String(timeout))
    const next = await saveQueryTimeout(typed)
    setDraft(String(next))
    setTimeout(next)
  }

  return (
    <label
      className="glass-chip flex shrink-0 items-center gap-1 py-1.5 pl-3 pr-2 text-xs text-slate-300"
      title="Seconds one query may take before it is given up on"
    >
      Timeout
      <input
        type="number"
        min={1}
        data-testid="query-timeout"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void apply()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
        }}
        className="glass-input w-14 px-1.5 py-0.5 text-xs"
      />
      s
    </label>
  )
}
