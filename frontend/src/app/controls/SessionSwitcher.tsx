import { useEffect, useRef, useState } from 'react'

import { useDismiss } from '../../core'
import {
  listSessions,
  removeSession,
  renameSession,
  selectSession,
  sessionId,
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
  const current = sessionId()
  const [open, setOpen] = useState(false)
  const [list, setList] = useState<SessionSummary[]>([])
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState('')
  // Enter and Escape both unmount the input, which can fire a trailing blur.
  const editing = useRef(false)
  const [error, setError] = useState('')
  // Off while renaming: the input's focus-out save must run before the menu unmounts.
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

  function startRename() {
    setDraft(label)
    editing.current = true
    setRenaming(true)
  }

  function cancelRename() {
    editing.current = false
    setRenaming(false)
  }

  // close: false when focus moved to another menu control, whose own action
  // (switch, delete, new) decides whether the menu stays.
  async function saveName(close: boolean) {
    if (!editing.current) return
    editing.current = false
    setRenaming(false)
    if (close) setOpen(false)
    const name = draft.trim()
    // An unchanged name would pin the automatic "Session <n>" label.
    if (name === label) return
    // renameSession answers with the label the server settled on, so clearing
    // the name (which unpins) needs no read-back.
    const next = await renameSession(name)
    // After a switch made meanwhile, `next` is the new session's label.
    if (sessionId() !== current) return
    setList((l) => l.map((s) => (s.id === current ? { ...s, label: next } : s)))
  }

  return (
    <div ref={rootRef} className="relative min-w-0">
      <button
        type="button"
        data-testid="session-switcher"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="glass-toggle flex max-w-full items-center gap-1.5 px-3 py-1.5 text-sm"
      >
        <span className="shrink-0 text-xs text-slate-400">Session</span>
        <span className="truncate font-medium">{label}</span>
        <span className="text-xs text-slate-400">▾</span>
      </button>
      {open && (
        <div
          data-testid="session-menu"
          role="listbox"
          className="glass-popover absolute right-0 top-full z-10 mt-2 flex max-h-80 w-72 flex-col p-1 text-sm"
        >
          <div className="overflow-auto">
            {list.map((s) => {
              const isCurrent = s.id === current
              return (
                <div
                  key={s.id}
                  className={`flex items-center gap-1 rounded border-l-2 ${
                    isCurrent ? 'border-indigo-400 bg-indigo-500/15' : 'border-transparent'
                  }`}
                >
                  {isCurrent && renaming ? (
                    <input
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.nativeEvent.isComposing) void saveName(true)
                        if (e.key === 'Escape') {
                          // cancelRename re-arms the menu's Escape dismiss before this
                          // event reaches document, so keep it from closing the menu.
                          e.stopPropagation()
                          cancelRename()
                        }
                      }}
                      onBlur={(e) => void saveName(!rootRef.current?.contains(e.relatedTarget))}
                      aria-label="Session name"
                      data-testid="session-rename-input"
                      autoFocus
                      className="glass-input m-0.5 min-w-0 flex-1 px-2 py-1 text-sm"
                    />
                  ) : (
                    <>
                      <button
                        type="button"
                        role="option"
                        aria-selected={isCurrent}
                        disabled={s.held && !isCurrent}
                        data-testid={`session-row-${s.id}`}
                        onClick={() => void switchTo(s.id)}
                        className={`flex-1 truncate rounded px-2 py-1.5 text-left hover:bg-white/10 disabled:text-slate-500 disabled:hover:bg-transparent ${
                          isCurrent ? 'font-medium text-indigo-100' : 'text-slate-200'
                        }`}
                      >
                        {isCurrent && (
                          <span aria-hidden className="mr-1.5 text-indigo-300">
                            ✓
                          </span>
                        )}
                        {s.label}
                        {isCurrent && (
                          <span className="ml-2 text-xs text-indigo-300">this tab</span>
                        )}
                        {s.connection && (
                          <span className="ml-2 text-xs text-slate-400">
                            {s.database ? `${s.connection} · ${s.database}` : s.connection}
                          </span>
                        )}
                        {s.held && !isCurrent && (
                          <span className="ml-2 text-xs text-slate-400">in another tab</span>
                        )}
                      </button>
                      {isCurrent && s.renamable !== false && (
                        <button
                          type="button"
                          aria-label="Rename this session"
                          title="Rename"
                          data-testid="session-rename"
                          onClick={startRename}
                          className="rounded px-2 py-1.5 text-slate-300 hover:bg-white/10"
                        >
                          <svg
                            viewBox="0 0 24 24"
                            className="h-3.5 w-3.5"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          >
                            <path d="M12 20h9" />
                            <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
                          </svg>
                        </button>
                      )}
                    </>
                  )}
                  {/* A held session (this tab's or another's) and the Agent session can't be deleted. */}
                  {s.deletable && (
                    <button
                      type="button"
                      aria-label={`Delete ${s.label}`}
                      data-testid={`session-delete-${s.id}`}
                      onClick={() => void remove(s.id)}
                      className="rounded px-2 py-1.5 text-slate-400 hover:bg-white/10"
                    >
                      ×
                    </button>
                  )}
                </div>
              )
            })}
          </div>
          {error && <p className="px-2 py-1.5 text-xs text-amber-300">{error}</p>}
          <div className="mt-1 border-t border-white/10 pt-1">
            <button
              type="button"
              data-testid="session-new"
              onClick={() => void switchTo(null)}
              className="block w-full rounded px-2 py-1.5 text-left text-indigo-200 hover:bg-white/10"
            >
              New session
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
