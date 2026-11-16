// `<qv-chip query column label>`: one value of a dashboard query as a KPI pill.
// Reads the up-front results in `window.queries` and re-reads them on every
// re-run, as ParamSelect does; the query stays the page's (see docs/dashboard.md).

import { useEffect, useState } from 'react'

import type { DashboardResults } from '../dashboard/srcDoc'
import { chipValue } from '../dashboard/widgetChannel'
import { onParamsResults } from './frameChannel'

const results = () => (window as Window & { queries?: DashboardResults }).queries

export function Chip({
  query,
  column,
  label,
}: {
  query: string
  column: string | null
  label: string | null
}) {
  const [shown, setShown] = useState(() => chipValue(results(), query, column))

  // The prologue's listener runs first, so window.queries is already updated.
  useEffect(
    () => onParamsResults(() => setShown(chipValue(results(), query, column))),
    [query, column],
  )

  if ('error' in shown) {
    return (
      <span data-testid="qv-error" className="text-sm text-red-300">
        {shown.error}
      </span>
    )
  }
  return (
    <span className="inline-flex items-baseline gap-2 rounded-full bg-slate-900 px-3 py-1 text-sm text-slate-200">
      {label && <span className="text-slate-400">{label}</span>}
      <span
        data-testid="qv-chip"
        className="font-semibold tabular-nums text-[var(--qv-accent-text)]"
      >
        {shown.value}
      </span>
    </span>
  )
}
