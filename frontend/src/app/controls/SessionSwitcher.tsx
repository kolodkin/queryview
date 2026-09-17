import { useEffect, useState } from 'react'

import { useDismiss } from './useDismiss'
import {
  listSessions,
  removeSession,
  renameSession,
  selectSession,
  type SessionState,
  type SessionSummary,
} from '../session'

type Props = {
  label: string
  onSwitch: (session: SessionState) => void
}

// Header dropdown listing every session. A session held by another live tab is
// shown but not selectable: two tabs on one session would overwrite each
// other's state, which is the whole point of the per-tab claim.
export default function SessionSwitcher({ label, onSwitch }: Props) {
  const [open, setOpen] = useState(false)
  const [list, setList] = useState<SessionSummary[]>([])
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  // Only the menu light-dismisses: the rename row holds unsaved input.
  const rootRef = useDismiss<HTMLDivElement>(open && !renaming, () => setOpen(false))

  async function reload() {
    try {
      setList(await listSessions())
    } catch {
      /* keep the last list */
    }
  }

  useEffect(() => {
    if (!open) return
    // setList runs after the fetch await, so it doesn't cascade renders.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload()
  }, [open])

  async function switchTo(id: string | null) {
    setError('')
    const next = await selectSession(id)
    if (!next) {
      setError('That session is open in another tab.')
      await reload()
      return
    }
    setOpen(false)
    onSwitch(next)
  }

  async function remove(id: string) {
    const r = await removeSession(id)
    if (!r.ok) {
      setError(r.message ?? 'delete failed')
      return
    }
    await reload()
  }

  async function saveName() {
    await renameSession(draft.trim())
    setRenaming(false)
    setOpen(false)
    await reload()
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        data-testid="session-switcher"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="glass-toggle px-3 py-1.5 text-sm"
      >
        {label} <span className="text-xs text-slate-400">▾</span>
      </button>
      {open && (
        <div
          data-testid="session-menu"
          role="listbox"
          className="glass-popover absolute right-0 top-full z-10 mt-2 flex max-h-96 w-72 flex-col p-1 text-sm"
        >
          <div className="overflow-auto">
            {list.map((s) => (
              <div key={s.id} className="flex items-center gap-1">
                <button
                  type="button"
                  role="option"
                  aria-selected={s.label === label}
                  disabled={s.held && s.label !== label}
                  data-testid={`session-row-${s.id}`}
                  onClick={() => void switchTo(s.id)}
                  className="flex-1 truncate rounded px-2 py-1.5 text-left text-slate-200 hover:bg-white/10 disabled:text-slate-500 disabled:hover:bg-transparent"
                >
                  {s.label}
                  {s.held && s.label !== label && (
                    <span className="ml-2 text-xs text-slate-400">in another tab</span>
                  )}
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${s.label}`}
                  data-testid={`session-delete-${s.id}`}
                  onClick={() => void remove(s.id)}
                  className="rounded px-2 py-1.5 text-slate-400 hover:bg-white/10"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          {error && <p className="px-2 py-1.5 text-xs text-amber-300">{error}</p>}
          <div className="mt-1 border-t border-white/10 pt-1">
            {renaming ? (
              <form
                className="flex gap-1 p-1"
                onSubmit={(e) => {
                  e.preventDefault()
                  void saveName()
                }}
              >
                <input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  aria-label="Session name"
                  data-testid="session-rename-input"
                  autoFocus
                  className="glass-input w-full px-2 py-1 text-sm"
                />
                <button type="submit" className="glass-btn px-2 py-1 text-xs">
                  Save
                </button>
              </form>
            ) : (
              <>
                <button
                  type="button"
                  data-testid="session-new"
                  onClick={() => void switchTo(null)}
                  className="block w-full rounded px-2 py-1.5 text-left text-indigo-200 hover:bg-white/10"
                >
                  New session
                </button>
                <button
                  type="button"
                  data-testid="session-rename"
                  onClick={() => {
                    setDraft(label)
                    setRenaming(true)
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left text-slate-200 hover:bg-white/10"
                >
                  Rename this session
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
