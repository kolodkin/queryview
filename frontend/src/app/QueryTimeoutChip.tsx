// The header's Query timeout chip (docs/queryview.md): the seconds one request
// to the database may take, remembered with the session. The shell keys it by
// session, so a switch shows that session's value.

import { NumberInput } from './NumberInput'
import { useNumberSetting } from './useNumberSetting'
import type { NumberSetting } from './numberSetting'

const QUERY_TIMEOUT: NumberSetting = { view: 'app', key: 'queryTimeout', fallback: 30, max: 600 }

export function QueryTimeoutChip() {
  const field = useNumberSetting(QUERY_TIMEOUT)
  return (
    <label
      className="glass-chip flex shrink-0 items-center gap-1 py-1.5 pl-3 pr-2 text-xs text-slate-300"
      title="Seconds one query may take before it is given up on"
    >
      Timeout
      <NumberInput field={field} testid="query-timeout" className="w-14 rounded-[2px]" />s
    </label>
  )
}
