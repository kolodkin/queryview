import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { filterNames } from '../core'
import { isReady, type Connection } from './connection'
import { DRIVERS, type DriverMeta } from './drivers'
import { Loading, Spinner } from './controls/Spinner'
import { timeAgo } from './timeAgo'
import { apiFetch } from './api'

type TestResult = { ok: boolean; message: string }

// A saved connection's card data, from /api/db/connections.
type SavedConnection = {
  name: string
  type: string
  database: string | null
  last_active_at: number
}

// Past this many saved connections the cards get a filter box.
const FILTER_THRESHOLD = 6

// The Connect page (`/connect`): saved-connection cards and a "new connection"
// card per driver. See docs/queryview.md.
function ConnectView({
  connection,
  setConnection,
}: {
  connection: Connection | null
  setConnection: (c: Connection | null) => void
}) {
  const navigate = useNavigate()
  const [saved, setSaved] = useState<SavedConnection[] | null>(null)
  const [filter, setFilter] = useState('')
  // The driver whose form is open, if any.
  const [formType, setFormType] = useState<string | null>(null)
  // Back from the picker to the cards; the opened connection stays.
  const [browsing, setBrowsing] = useState(false)
  // The card being opened, for its spinner; and the last open's failure.
  const [opening, setOpening] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refreshSaved = useCallback(async () => {
    try {
      const data = await (await apiFetch('/api/db/connections')).json()
      setSaved(Array.isArray(data.connections) ? (data.connections as SavedConnection[]) : [])
    } catch {
      setSaved((s) => s ?? [])
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshSaved()
  }, [refreshSaved])

  const visible = useMemo(
    () => filterNames(saved ?? [], filter, (c) => c.name),
    [saved, filter],
  )

  // Land where an opened connection belongs: a ready one browses its tables,
  // the rest stay here on the database picker.
  function adopt(opened: Connection) {
    setConnection(opened)
    setFormType(null)
    setBrowsing(false)
    setError(null)
    void refreshSaved()
    if (isReady(opened)) navigate('/explorer')
  }

  async function openSaved(name: string) {
    setOpening(name)
    setError(null)
    try {
      const res = await apiFetch('/api/db/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const data = await res.json()
      if (!data.ok) {
        setError(data.message ?? `could not open “${name}”`)
        return
      }
      adopt({
        name: data.name as string,
        type: (data.type ?? 'clickhouse') as string,
        databases: (data.databases ?? []) as string[],
        database: null,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'request failed')
    } finally {
      setOpening(null)
    }
  }

  async function selectDatabase(database: string) {
    if (!connection) return
    const res = await apiFetch('/api/db/database', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ database }),
    })
    if (res.ok) {
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

  const heading = (
    <div className="mb-8 text-center">
      <h1 className="text-3xl font-bold tracking-tight text-white [text-shadow:0_2px_30px_rgba(129,140,248,0.45)]">
        QueryView
      </h1>
      <p className="mt-2 text-sm text-slate-400">
        {formType ? 'Create a connection' : picking ? 'Pick a database' : 'Choose a connection'}
      </p>
    </div>
  )

  if (formType && DRIVERS[formType]) {
    return (
      <div className="w-full max-w-md" data-testid="connect-page">
        {heading}
        <ConnectionForm
          meta={DRIVERS[formType]}
          onBack={() => setFormType(null)}
          onConnected={(name, type, databases) =>
            adopt({ name, type, databases, database: null })
          }
        />
      </div>
    )
  }

  if (picking && connection) {
    const remembered = saved?.find((c) => c.name === connection.name)?.database ?? null
    return (
      <div className="w-full max-w-3xl" data-testid="connect-page">
        {heading}
        <DatabasePicker
          connection={connection}
          remembered={remembered}
          onSelect={(db) => void selectDatabase(db)}
          onBack={() => setBrowsing(true)}
        />
      </div>
    )
  }

  const active = connection?.name ?? null
  const count = saved?.length ?? 0

  return (
    <div className="w-full max-w-3xl" data-testid="connect-page">
      {heading}

      <section aria-labelledby="saved-heading">
        <div className="mb-3 flex items-center gap-3">
          <h2 id="saved-heading" className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Saved connections
          </h2>
          {count > FILTER_THRESHOLD && (
            <form
              className="ml-auto w-56"
              onSubmit={(e) => {
                // Enter opens the first match, so a typed prefix is enough.
                e.preventDefault()
                if (visible.length > 0) void openSaved(visible[0].name)
              }}
            >
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder={`Filter ${count} connections…`}
                aria-label="Filter connections"
                data-testid="conn-filter"
                autoFocus
                autoComplete="off"
                className="glass-input w-full px-3 py-1.5 text-sm"
              />
            </form>
          )}
        </div>

        {saved === null ? (
          <Loading label="Loading connections…" />
        ) : count === 0 ? (
          <p data-testid="conn-empty" className="glass-panel p-5 text-center text-sm text-slate-400">
            No saved connections yet — create one below.
          </p>
        ) : visible.length === 0 ? (
          <p data-testid="conn-filter-empty" className="text-sm text-slate-400">
            No connections match “{filter.trim()}”.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {visible.map((c) => (
              <SavedCard
                key={c.name}
                conn={c}
                active={c.name === active}
                busy={opening === c.name}
                disabled={opening !== null}
                onOpen={() => void openSaved(c.name)}
              />
            ))}
          </div>
        )}

        {error && (
          <p data-testid="connect-error" className="mt-3 text-sm text-red-300">
            {error}
          </p>
        )}
      </section>

      <section aria-labelledby="new-heading" className="mt-8">
        <h2 id="new-heading" className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
          New connection
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {Object.values(DRIVERS).map((d) => (
            <button
              key={d.type}
              type="button"
              data-testid={`new-conn-${d.type}`}
              onClick={() => {
                setFormType(d.type)
                setError(null)
              }}
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
          ))}
        </div>
      </section>
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
  busy,
  disabled,
  onOpen,
}: {
  conn: SavedConnection
  active: boolean
  busy: boolean
  disabled: boolean
  onOpen: () => void
}) {
  const label = DRIVERS[conn.type]?.label ?? conn.type
  return (
    <button
      type="button"
      data-testid="conn-card"
      data-conn={conn.name}
      data-active={active}
      onClick={onOpen}
      disabled={disabled}
      title={`Open ${conn.name}`}
      className={`glass-card flex flex-col gap-3 p-4 text-left ${active ? 'is-active' : ''}`}
    >
      <span className="flex w-full items-center gap-3">
        <DriverMark type={conn.type} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-slate-100">{conn.name}</span>
          <span className="block text-xs text-slate-400">{label}</span>
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
    </button>
  )
}

function ConnectionForm({
  meta,
  onBack,
  onConnected,
}: {
  meta: DriverMeta
  onBack: () => void
  onConnected: (name: string, type: string, databases: string[]) => void
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(meta.fields.map((f) => [f.key, f.default])),
  )
  const [result, setResult] = useState<TestResult | null>(null)
  const [busy, setBusy] = useState(false)

  function body() {
    return JSON.stringify({ type: meta.type, ...values })
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
        onConnected(
          data.name as string,
          (data.type ?? meta.type) as string,
          (data.databases ?? []) as string[],
        )
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
        <h2 className="flex-1 text-lg font-semibold">New {meta.label} connection</h2>
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
            className={`mt-1 ${fieldClass}`}
          />
        </label>
      ))}

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
          Connect
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
          <button
            key={db}
            type="button"
            onClick={() => onSelect(db)}
            data-testid="db-option"
            data-db={db}
            title={db === remembered ? 'Last used' : undefined}
            className={`glass-toggle px-3 py-1.5 text-sm ${db === remembered ? 'is-active-soft' : ''}`}
          >
            {db}
          </button>
        ))}
      </div>
    </section>
  )
}

export default ConnectView
