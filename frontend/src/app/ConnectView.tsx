import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { filterNames, useDismiss } from '../core'
import {
  isReady,
  deleteConnection,
  fetchSavedConfig,
  lockConnection,
  explorerUrl,
  openSaved,
  removeLock,
  unlockConnection,
  useFreshDatabases,
  selectDatabase,
  toConnection,
  type Connection,
  type LockResult,
} from './connection'
import { DRIVERS, type DriverMeta } from './drivers'
import { Loading, Spinner } from './controls/Spinner'
import { AgentBadge } from './controls/AgentBadge'
import { CopyName } from './controls/CopyName'
import { PassphrasePrompt } from './controls/PassphrasePrompt'
import { timeAgo } from './timeAgo'
import {
  MANY_THRESHOLD,
  RECENT_COUNT,
  driverCounts,
  fetchConnections,
  labelOf,
  matchConnections,
  type SavedConnection,
} from './savedConnections'
import { apiFetch } from './api'

type TestResult = { ok: boolean; message: string }

// What the passphrase prompt is for, and the call it makes; `edit` only
// unlocks, the form opens once the tab holds the token.
type PromptKind = 'lock' | 'unlock' | 'edit' | 'delete'
const PROMPT_CALLS: Record<PromptKind, (name: string, passphrase: string) => Promise<LockResult>> =
  {
    lock: lockConnection,
    unlock: removeLock,
    edit: unlockConnection,
    delete: deleteConnection,
  }
const PROMPT_TITLES: Record<PromptKind, (name: string) => [string, string]> = {
  lock: (name) => [`Lock ${name} with a passphrase`, 'Lock'],
  unlock: (name) => [`Remove the lock from ${name}`, 'Remove lock'],
  edit: (name) => [`${name} is locked`, 'Unlock'],
  delete: (name) => [`Delete ${name}? Its passphrase confirms.`, 'Delete'],
}

const sectionLabel = 'text-xs font-semibold uppercase tracking-wider text-slate-400'
const cardGrid = 'grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3'

// The Connect page (`/connect`): saved-connection cards and a "new connection"
// card per driver. See docs/queryview.md.
function ConnectView({
  connection,
  setConnection,
  listNonce,
}: {
  connection: Connection | null
  setConnection: React.Dispatch<React.SetStateAction<Connection | null>>
  // Bumped when a session connection is added or removed.
  listNonce: number
}) {
  const navigate = useNavigate()
  const [saved, setSaved] = useState<SavedConnection[] | null>(null)
  const [filter, setFilter] = useState('')
  // The "many" layout's driver chip and keyboard-highlighted card, and the
  // "+ New" menu (the only new-connection entry once the cards are hidden).
  const [driver, setDriver] = useState<string | null>(null)
  const [highlight, setHighlight] = useState(0)
  const [newOpen, setNewOpen] = useState(false)
  const newRef = useDismiss<HTMLDivElement>(newOpen, () => setNewOpen(false))
  const searchRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  // The driver whose form is open, if any; `editing` holds a saved
  // connection's values when the form edits one instead of creating.
  const [formType, setFormType] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ name: string; values: Record<string, string> } | null>(
    null,
  )
  // Back from the picker to the cards; the opened connection stays.
  const [browsing, setBrowsing] = useState(false)
  // The card being opened, for its spinner; and the last open's failure.
  const [opening, setOpening] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // The passphrase prompt up, if any: to lock a card, remove its lock, or
  // edit or delete a locked one (docs/connect.md#locked-connections). Opening
  // a locked card needs none: the shell asks once the session lands on it.
  const [prompt, setPrompt] = useState<{ kind: PromptKind; name: string } | null>(null)

  const refreshSaved = useCallback(async () => {
    try {
      setSaved(await fetchConnections())
    } catch {
      setSaved((s) => s ?? [])
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshSaved()
  }, [refreshSaved, listNonce])

  const count = saved?.length ?? 0
  const many = count > MANY_THRESHOLD
  const visible = useMemo(
    () => matchConnections(saved ?? [], filter, driver),
    [saved, filter, driver],
  )
  const drivers = useMemo(() => (many ? driverCounts(saved ?? []) : []), [many, saved])
  // Unfiltered, the first (most recent) few form the Recent row: a split, not a copy.
  const recentCount = many && !filter.trim() && !driver ? RECENT_COUNT : 0
  const current = Math.min(highlight, Math.max(visible.length - 1, 0))

  // `/` jumps to the search box from anywhere on the page but a text field.
  useEffect(() => {
    if (!many) return
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (e.key !== '/' || el.closest('input, textarea, select')) return
      e.preventDefault()
      searchRef.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [many])

  // Keep the highlighted card in view inside the scrolling list — also when a
  // new search leaves it at index 0 while the list sits scrolled down.
  useEffect(() => {
    listRef.current
      ?.querySelector('[data-highlighted="true"]')
      ?.scrollIntoView({ block: 'nearest' })
  }, [current, visible])

  function onSearchKey(e: React.KeyboardEvent<HTMLInputElement>) {
    const steps: Record<string, number> = {
      ArrowDown: 1,
      ArrowRight: 1,
      ArrowUp: -1,
      ArrowLeft: -1,
    }
    const step = steps[e.key]
    if (step === undefined || visible.length === 0) return
    e.preventDefault()
    setHighlight((current + step + visible.length) % visible.length)
  }

  // Land where an opened connection belongs: a ready one browses its tables,
  // the rest stay here on the database picker (with the card list refreshed,
  // since a new connection isn't in it yet).
  function adopt(opened: Connection) {
    setConnection(opened)
    closeForm()
    setBrowsing(false)
    setError(null)
    if (isReady(opened)) navigate(explorerUrl(opened))
    else void refreshSaved()
  }

  async function open(name: string) {
    setOpening(name)
    setError(null)
    const r = await openSaved(name)
    setOpening(null)
    if (r.ok) adopt(r.connection)
    else setError(r.message)
  }

  // The prompt's answer: an error to show, or null once the action went through.
  async function submitPassphrase(passphrase: string): Promise<string | null> {
    if (!prompt) return null
    const { kind, name } = prompt
    const r = await PROMPT_CALLS[kind](name, passphrase)
    if (!r.ok) return r.message
    setPrompt(null)
    if (kind === 'edit') await edit(name)
    else await afterChange(name)
    return null
  }

  // The list after a lock change or a delete; a deleted active connection is gone.
  async function afterChange(name: string) {
    if (prompt?.kind === 'delete' && connection?.name === name) setConnection(null)
    await refreshSaved()
  }

  function closeForm() {
    setFormType(null)
    setEditing(null)
  }

  // Open the driver form on a saved connection's values. A locked one asks
  // for its passphrase first unless this tab holds the token.
  async function edit(name: string) {
    setError(null)
    const r = await fetchSavedConfig(name)
    if (r.ok) {
      setEditing({ name, values: r.values })
      setFormType(r.type)
      setNewOpen(false)
    } else if (r.locked) setPrompt({ kind: 'edit', name })
    else setError(r.message)
  }

  async function remove(conn: SavedConnection) {
    setError(null)
    if (conn.locked) return setPrompt({ kind: 'delete', name: conn.name })
    if (!window.confirm(`Delete connection '${conn.name}'?`)) return
    const r = await deleteConnection(conn.name)
    if (!r.ok) return setError(r.message)
    if (connection?.name === conn.name) setConnection(null)
    await refreshSaved()
  }

  async function pickDatabase(database: string) {
    if (!connection) return
    if (await selectDatabase(database)) {
      setConnection({ ...connection, database })
      navigate('/explorer')
    }
  }

  const picking =
    !formType &&
    !browsing &&
    !!connection &&
    connection.database === null &&
    connection.databases.length > 0

  useFreshDatabases(picking, setConnection)

  const heading = (
    <div className="mb-8 text-center">
      <h1 className="text-3xl font-bold tracking-tight text-white [text-shadow:0_2px_30px_rgba(129,140,248,0.45)]">
        QueryView
      </h1>
      <p className="mt-2 text-sm text-slate-400">
        {formType
          ? editing
            ? 'Edit a connection'
            : 'Create a connection'
          : picking
            ? 'Pick a database'
            : 'Choose a connection'}
      </p>
    </div>
  )

  const form = formType ? DRIVERS[formType] : undefined
  const active = connection?.name ?? null
  const [promptTitle, promptAction] = prompt ? PROMPT_TITLES[prompt.kind](prompt.name) : ['', '']

  function startNew(type: string) {
    setEditing(null)
    setFormType(type)
    setNewOpen(false)
    setError(null)
  }

  // Cards for visible[from..to), highlighted by their index in `visible`.
  const cards = (from: number, to?: number) =>
    visible
      .slice(from, to)
      .map((c, i) => (
        <SavedCard
          key={c.name}
          conn={c}
          active={c.name === active}
          highlighted={many && from + i === current}
          busy={opening === c.name}
          disabled={opening !== null}
          onOpen={() => void open(c.name)}
          onToggleLock={() => setPrompt({ kind: c.locked ? 'unlock' : 'lock', name: c.name })}
          onEdit={() => void edit(c.name)}
          onDelete={() => void remove(c)}
        />
      ))

  const newCards = Object.values(DRIVERS).map((d) => (
    <button
      key={d.type}
      type="button"
      data-testid={`new-conn-${d.type}`}
      onClick={() => startNew(d.type)}
      className="glass-card group flex items-center gap-3 p-4 text-left"
    >
      <DriverMark type={d.type} />
      <span className="min-w-0">
        <span className="block font-medium text-slate-100">{d.label}</span>
        <span className="block text-xs text-slate-400">{d.blurb}</span>
      </span>
      <span className="ml-auto text-lg text-slate-500 group-hover:text-indigo-200" aria-hidden>
        +
      </span>
    </button>
  ))

  return (
    <div className={`w-full ${form ? 'max-w-md' : 'max-w-3xl'}`} data-testid="connect-page">
      {prompt && (
        <PassphrasePrompt
          title={promptTitle}
          action={promptAction}
          onSubmit={submitPassphrase}
          onCancel={() => setPrompt(null)}
        />
      )}
      {heading}
      {form ? (
        <ConnectionForm
          key={editing?.name ?? 'new'}
          meta={form}
          editing={editing?.values ?? null}
          onBack={closeForm}
          onConnected={adopt}
        />
      ) : picking ? (
        <DatabasePicker
          connection={connection}
          remembered={saved?.find((c) => c.name === connection.name)?.database ?? null}
          onSelect={(db) => void pickDatabase(db)}
          onBack={() => setBrowsing(true)}
        />
      ) : (
        <>
          <section aria-labelledby="saved-heading">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <h2 id="saved-heading" className={sectionLabel}>
                Saved connections
              </h2>
              {many && (
                <>
                  <span data-testid="conn-count" className="text-xs text-slate-500">
                    {visible.length} of {count}
                  </span>
                  <form
                    className="ml-auto w-56"
                    onSubmit={(e) => {
                      // Enter opens the highlighted card.
                      e.preventDefault()
                      if (visible.length > 0) void open(visible[current].name)
                    }}
                  >
                    <input
                      ref={searchRef}
                      type="search"
                      value={filter}
                      onChange={(e) => {
                        setFilter(e.target.value)
                        setHighlight(0)
                      }}
                      onKeyDown={onSearchKey}
                      placeholder="Search…  ( / )"
                      title="Matches name, driver and last database"
                      aria-label="Search connections"
                      data-testid="conn-filter"
                      autoFocus
                      autoComplete="off"
                      className="glass-input w-full px-3 py-1.5 text-sm"
                    />
                  </form>
                </>
              )}
              <div ref={newRef} className={`relative ${many ? '' : 'ml-auto'}`}>
                <button
                  type="button"
                  data-testid="new-menu-toggle"
                  aria-expanded={newOpen}
                  onClick={() => setNewOpen((o) => !o)}
                  className="glass-btn-primary px-3 py-1.5 text-sm font-medium"
                >
                  + New ▾
                </button>
                {newOpen && (
                  <div
                    data-testid="new-menu"
                    className="glass-popover absolute right-0 top-full z-10 mt-2 flex w-72 flex-col gap-2 p-2"
                  >
                    {newCards}
                  </div>
                )}
              </div>
            </div>

            {drivers.length > 1 && (
              <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Filter by driver">
                {[[null, count] as const, ...drivers].map(([t, n]) => (
                  <button
                    key={t ?? 'all'}
                    type="button"
                    data-testid="driver-chip"
                    data-type={t ?? ''}
                    aria-pressed={driver === t}
                    onClick={() => {
                      setDriver(t)
                      setHighlight(0)
                    }}
                    className={`glass-toggle px-3 py-1 text-xs ${driver === t ? 'is-active' : ''}`}
                  >
                    {t === null ? 'All' : labelOf(t)} {n}
                  </button>
                ))}
              </div>
            )}

            {saved === null ? (
              <Loading label="Loading connections…" />
            ) : count === 0 ? (
              <p
                data-testid="conn-empty"
                className="glass-panel p-5 text-center text-sm text-slate-400"
              >
                No saved connections yet — create one below.
              </p>
            ) : visible.length === 0 ? (
              <p data-testid="conn-filter-empty" className="text-sm text-slate-400">
                No connections match{filter.trim() ? ` “${filter.trim()}”` : ''}.
              </p>
            ) : (
              <div ref={listRef}>
                {recentCount > 0 && (
                  <>
                    <h3 className={`mb-2 ${sectionLabel}`}>Recent</h3>
                    <div data-testid="conn-recent" className={cardGrid}>
                      {cards(0, recentCount)}
                    </div>
                    <h3 className={`mb-2 mt-5 ${sectionLabel}`}>All connections</h3>
                  </>
                )}
                {visible.length > recentCount && (
                  // Capped so the page never grows; padding keeps the hover lift unclipped.
                  <div
                    data-testid="conn-all"
                    className={
                      many ? `-m-1 max-h-[22rem] overflow-y-auto p-1 ${cardGrid}` : cardGrid
                    }
                  >
                    {cards(recentCount)}
                  </div>
                )}
              </div>
            )}

            {error && (
              <p data-testid="connect-error" className="mt-3 text-sm text-red-300">
                {error}
              </p>
            )}
          </section>

          {!many && (
            <section aria-labelledby="new-heading" className="mt-8">
              <h2 id="new-heading" className={`mb-3 ${sectionLabel}`}>
                New connection
              </h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">{newCards}</div>
            </section>
          )}
        </>
      )}
    </div>
  )
}

// The driver's tinted monogram; an unknown type gets a neutral one.
function DriverMark({ type }: { type: string }) {
  const meta = DRIVERS[type]
  return (
    <span
      aria-hidden
      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-xs font-bold ring-1 ${
        meta?.accent ?? 'bg-white/10 text-slate-200 ring-white/20'
      }`}
    >
      {meta?.mark ?? type.slice(0, 2).toUpperCase()}
    </span>
  )
}

function SavedCard({
  conn,
  active,
  highlighted,
  busy,
  disabled,
  onOpen,
  onToggleLock,
  onEdit,
  onDelete,
}: {
  conn: SavedConnection
  active: boolean
  highlighted: boolean
  busy: boolean
  disabled: boolean
  onOpen: () => void
  onToggleLock: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const label = labelOf(conn.type)
  const saved = conn.scope !== 'session'
  // Buttons inside the card stop the click from opening it.
  const inCard = (f: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation()
    f()
  }
  // A div, not a button: the lock toggle inside it is a button of its own.
  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      data-testid="conn-card"
      data-conn={conn.name}
      data-active={active}
      data-highlighted={highlighted}
      data-locked={!!conn.locked}
      onClick={disabled ? undefined : onOpen}
      onKeyDown={(e) => {
        if (disabled || (e.key !== 'Enter' && e.key !== ' ')) return
        e.preventDefault()
        onOpen()
      }}
      aria-disabled={disabled}
      title={`Open ${conn.name}`}
      className={`glass-card flex cursor-pointer gap-3 p-4 text-left ${active ? 'is-active' : ''} ${
        highlighted ? 'is-highlighted' : ''
      } ${disabled ? 'cursor-wait opacity-50' : ''}`}
    >
      <span className="flex min-w-0 flex-1 flex-col gap-3">
        <span className="flex w-full items-center gap-3">
          <DriverMark type={conn.type} />
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium text-slate-100">{conn.name}</span>
            <span className="block text-xs text-slate-400">
              {label}
              <AgentBadge conn={conn} className="ml-2" />
            </span>
          </span>
          {busy ? (
            <Spinner />
          ) : (
            active && (
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-500"
                aria-label="active connection"
              />
            )
          )}
        </span>
        <span className="flex w-full items-center justify-between gap-2 text-xs text-slate-500">
          <span className="truncate font-mono text-slate-300">{conn.database ?? '—'}</span>
          <span className="shrink-0">{timeAgo(conn.last_active_at)}</span>
        </span>
      </span>
      {/* The card's controls, stacked on its right edge: lock, edit, delete. */}
      <span className="flex shrink-0 flex-col gap-1">
        {saved && (
          <button
            type="button"
            data-testid="conn-lock"
            onClick={inCard(onToggleLock)}
            disabled={disabled}
            aria-label={conn.locked ? `Remove the lock from ${conn.name}` : `Lock ${conn.name}`}
            title={
              conn.locked
                ? 'Locked: the agent is kept off. Click to remove the lock.'
                : 'Lock behind a passphrase'
            }
            className={`glass-btn px-2 py-0.5 text-xs ${conn.locked ? 'text-amber-300' : 'text-slate-500'}`}
          >
            {conn.locked ? '🔒' : '🔓'}
          </button>
        )}
        {saved && (
          <button
            type="button"
            data-testid="conn-edit"
            onClick={inCard(onEdit)}
            disabled={disabled}
            aria-label={`Edit ${conn.name}`}
            title="Edit the connection"
            className="glass-btn px-2 py-0.5 text-xs text-slate-500"
          >
            ✎
          </button>
        )}
        <button
          type="button"
          data-testid="conn-delete"
          onClick={inCard(onDelete)}
          disabled={disabled}
          aria-label={`Delete ${conn.name}`}
          title="Delete the connection"
          className="glass-btn px-2 py-0.5 text-xs text-slate-500 hover:text-red-300"
        >
          ✕
        </button>
      </span>
    </div>
  )
}

function ConnectionForm({
  meta,
  editing,
  onBack,
  onConnected,
}: {
  meta: DriverMeta
  // A saved connection's values: the form re-saves it under its name.
  editing: Record<string, string> | null
  onBack: () => void
  onConnected: (connection: Connection) => void
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(meta.fields.map((f) => [f.key, editing?.[f.key] ?? f.default])),
  )
  const [result, setResult] = useState<TestResult | null>(null)
  const [busy, setBusy] = useState(false)
  // Session only: kept in this session's memory, never saved.
  const [sessionOnly, setSessionOnly] = useState(false)

  function body() {
    return JSON.stringify({ type: meta.type, ...values, session: sessionOnly })
  }

  async function testConnection() {
    setBusy(true)
    setResult(null)
    try {
      const res = await apiFetch('/api/db/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body(),
      })
      setResult((await res.json()) as TestResult)
    } catch (err) {
      setResult({ ok: false, message: err instanceof Error ? err.message : 'request failed' })
    } finally {
      setBusy(false)
    }
  }

  async function connect() {
    setBusy(true)
    setResult(null)
    try {
      const res = await apiFetch('/api/db/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body(),
      })
      const data = await res.json()
      if (data.ok) {
        onConnected(toConnection({ type: meta.type, ...data }))
      } else {
        setResult({ ok: false, message: data.message ?? 'connect failed' })
      }
    } catch (err) {
      setResult({ ok: false, message: err instanceof Error ? err.message : 'request failed' })
    } finally {
      setBusy(false)
    }
  }

  const fieldClass = 'glass-input w-full px-3 py-2'

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        connect()
      }}
      data-testid={meta.formTestid}
      className="glass-panel space-y-4 p-6"
    >
      <div className="flex items-center gap-3">
        <DriverMark type={meta.type} />
        <h2 className="flex-1 text-lg font-semibold">
          {editing ? 'Edit' : 'New'} {meta.label} connection
        </h2>
        <BackButton testid="form-back" onClick={onBack} />
      </div>

      {meta.fields.map((f, i) => (
        <label key={f.key} className="block text-sm font-medium text-slate-300">
          {f.label}
          <input
            type={f.type}
            value={values[f.key]}
            onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
            aria-label={f.label}
            data-testid={f.testid}
            autoFocus={i === 0}
            readOnly={!!editing && f.key === 'name'}
            placeholder={editing && f.type === 'password' ? 'unchanged' : undefined}
            className={`mt-1 ${fieldClass} ${editing && f.key === 'name' ? 'opacity-60' : ''}`}
          />
        </label>
      ))}

      {!editing && (
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={sessionOnly}
            onChange={(e) => setSessionOnly(e.target.checked)}
            data-testid="conn-session-only"
          />
          Session only — don't save
        </label>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={testConnection}
          data-testid={meta.testTestid}
          disabled={busy}
          className="glass-btn flex-1 px-4 py-2 font-medium"
        >
          Test connection
        </button>
        <button
          type="submit"
          data-testid={meta.connectTestid}
          disabled={busy}
          className="glass-btn-primary flex-1 px-4 py-2 font-medium"
        >
          {editing ? 'Save & connect' : 'Connect'}
        </button>
      </div>

      {result && (
        <p
          data-testid={meta.resultTestid}
          data-ok={result.ok}
          className={`text-sm ${result.ok ? 'text-emerald-300' : 'text-red-300'}`}
        >
          {result.message}
        </p>
      )}
    </form>
  )
}

function BackButton({ testid, onClick }: { testid: string; onClick: () => void }) {
  return (
    <button
      type="button"
      data-testid={testid}
      onClick={onClick}
      className="glass-btn shrink-0 px-3 py-1 text-xs text-slate-300"
    >
      ← Connections
    </button>
  )
}

function DatabasePicker({
  connection,
  remembered,
  onSelect,
  onBack,
}: {
  connection: Connection
  // The database this connection was last on, highlighted as the likely pick.
  remembered: string | null
  onSelect: (database: string) => void
  onBack: () => void
}) {
  const [filter, setFilter] = useState('')
  const visible = useMemo(
    () => filterNames(connection.databases, filter),
    [connection.databases, filter],
  )
  return (
    <section data-testid="db-picker" className="glass-panel p-6">
      <div className="flex items-center gap-3">
        <DriverMark type={connection.type} />
        <h2 className="flex-1 text-sm font-medium text-slate-200">
          Connected to {connection.name}. Select a database:
        </h2>
        <BackButton testid="picker-back" onClick={onBack} />
      </div>
      <form
        className="mt-4"
        onSubmit={(e) => {
          // Enter picks the first match, so a typed prefix is enough.
          e.preventDefault()
          if (visible.length > 0) onSelect(visible[0])
        }}
      >
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={`Filter ${connection.databases.length} databases…`}
          aria-label="Filter databases"
          data-testid="db-filter"
          autoFocus
          autoComplete="off"
          className="glass-input w-full px-3 py-2 text-sm"
        />
      </form>
      {visible.length === 0 && (
        <p className="mt-3 text-sm text-slate-400" data-testid="db-filter-empty">
          No databases match “{filter.trim()}”.
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {visible.map((db) => (
          <div key={db} className="group flex items-center">
            <button
              type="button"
              onClick={() => onSelect(db)}
              data-testid="db-option"
              data-db={db}
              title={db === remembered ? 'Last used' : undefined}
              className={`glass-toggle px-3 py-1.5 text-sm ${db === remembered ? 'is-active-soft' : ''}`}
            >
              {db}
            </button>
            <CopyName name={db} testid="db-option-copy" />
          </div>
        ))}
      </div>
    </section>
  )
}

export default ConnectView
