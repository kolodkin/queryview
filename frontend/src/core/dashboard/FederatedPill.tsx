import { useState, type ReactNode } from 'react'

import { useDismiss } from '../useDismiss'
import type { FederatedConnection } from './entries'

const ICON: Record<FederatedConnection['status'], string> = {
  ok: '🟢',
  failed: '🔴',
  locked: '🔒',
  unknown: '⚪',
}

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

// The pill a federated dashboard shows in place of the session's connection
// (docs/system/queryview.md): its connections, and per connection the last
// run's status. Before the first reply it has the names alone. Without
// `onUnlock` (the viewer server) a locked row offers no Unlock. `children` is
// the dialog an Unlock opened: inside the pill, so a press in it keeps the list open.
export function FederatedPill({
  connections,
  onUnlock,
  children,
}: {
  connections: (FederatedConnection | string)[]
  onUnlock?: (name: string) => void
  children?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const ref = useDismiss<HTMLDivElement>(open, () => setOpen(false))
  const rows = connections.map((c) => (typeof c === 'string' ? { name: c } : c))
  return (
    <div ref={ref} className="relative min-w-0">
      <button
        type="button"
        data-testid="federated-pill"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="glass-chip flex max-w-full items-center gap-2 px-3 py-1.5 text-sm font-medium"
      >
        <span aria-hidden>⛓</span>
        <span className="truncate">
          Federated · {count(rows.length, 'connection', 'connections')}
        </span>
        <span className="text-xs text-slate-400">▾</span>
      </button>
      {open && (
        <ul className="glass-popover absolute left-0 top-full z-10 mt-2 w-96 p-1 text-sm">
          {rows.map((c, i) => (
            <li key={i} data-testid="federated-pill-row" className="rounded px-2 py-1.5">
              <div className="flex items-center gap-2">
                {'status' in c && <span>{ICON[c.status]}</span>}
                <span className="truncate text-slate-200">{c.name}</span>
                {'database' in c && c.database && (
                  <span className="truncate text-slate-400">· {c.database}</span>
                )}
                {'status' in c && c.status === 'locked' && onUnlock && (
                  <button
                    type="button"
                    data-testid="federated-unlock"
                    onClick={() => onUnlock(c.name)}
                    className="glass-btn px-2 py-0.5 text-xs"
                  >
                    Unlock
                  </button>
                )}
                {'queries' in c && (
                  <span className="ml-auto shrink-0 text-xs text-slate-400">
                    {count(c.queries.length, 'query', 'queries')}
                  </span>
                )}
              </div>
              {'status' in c && c.status === 'unknown' && (
                <div className="pl-6 text-xs text-slate-400">Not a connection here</div>
              )}
              {'status' in c && c.status === 'failed' && c.message && (
                <div className="pl-6 text-xs text-rose-300">{c.message}</div>
              )}
            </li>
          ))}
        </ul>
      )}
      {children}
    </div>
  )
}
