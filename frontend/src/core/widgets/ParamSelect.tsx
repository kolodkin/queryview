// `<qv-param name>`: the selector for one dashboard param, so a dashboard
// needn't draw its own. Reads `window.params` and asks for a re-run through
// `window.setParams`, the page's existing channel (see ../dashboard/srcDoc.ts).

import { useEffect, useState } from 'react'

import { MAX_TEXT_PARAM, type ResolvedParam } from '../dashboard/params'
import { onParamsResults } from './frameChannel'

type FrameWindow = Window & {
  params?: ResolvedParam[]
  setParams?: (values: Record<string, string | boolean>) => void
}

const frame = () => window as FrameWindow

export function ParamSelect({ name }: { name: string }) {
  const [params, setParams] = useState<ResolvedParam[]>(() => frame().params ?? [])

  // The prologue's listener was added first, so window.params is already
  // updated when this one runs.
  useEffect(() => onParamsResults(() => setParams([...(frame().params ?? [])])), [])

  const param = params.find((p) => p.name === name)
  // An `each` is a list nobody picks from: its queries run on every option.
  if (!param || param.kind === 'each') return null

  // Every selector's value goes along: the host re-defaults any it isn't sent.
  // Not a text's: the host keeps what was typed, which this copy may predate.
  function choose(value: string | boolean) {
    const values: Record<string, string | boolean> = {}
    for (const p of params) {
      if (p.kind !== 'text' && p.kind !== 'each')
        values[p.name] = p.kind === 'dimension' ? p.value !== '' : p.value
    }
    values[name] = value
    frame().setParams?.(values)
  }

  return (
    <label className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-2 py-1 text-sm text-slate-200">
      <span className="text-slate-400">{name}</span>
      {param.kind === 'text' ? (
        // Uncontrolled, keyed on the value: typing stays local until Enter or blur.
        <input
          type="text"
          data-testid="qv-param"
          key={param.value}
          defaultValue={param.value}
          maxLength={MAX_TEXT_PARAM}
          onKeyDown={(e) => {
            // Not the Enter that accepts an IME candidate.
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) e.currentTarget.blur()
          }}
          onBlur={(e) => e.target.value !== param.value && choose(e.target.value)}
          className="glass-input px-2 py-1 text-sm"
        />
      ) : param.kind === 'dimension' ? (
        <input
          type="checkbox"
          data-testid="qv-param"
          checked={param.value !== ''}
          onChange={(e) => choose(e.target.checked)}
        />
      ) : (
        <select
          data-testid="qv-param"
          value={param.value}
          onChange={(e) => choose(e.target.value)}
          className="glass-input px-2 py-1 text-sm"
        >
          {param.value === '' && <option value="">Select…</option>}
          {param.options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      )}
    </label>
  )
}
