import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  CellViewModal,
  FieldPickers,
  ResultsTable,
  applyParams,
  parseCellViewYaml,
  cellText,
  columnNames,
  columnTypes,
  parseQueryParams,
  presentationForSave,
  renderCell,
  shownColumnIndices,
  type CellViewMap,
  type Field,
  type OrderCol,
  type ParamDef,
  type ParamSpec,
  type QueryRows,
} from '../core'
import { isReady, type Connection } from './connection'
import { DRIVERS, type DriverMeta } from './drivers'
import ExportImportControls from './controls/ExportImportControls'
import GitSyncControls from './controls/GitSyncControls'
import { downloadText } from './yamlio'
import { activeWorkspace } from './workspace'
import { suggestCompletions, type Suggestion } from './promptSuggestions'
import { filterDatabases } from './databaseFilter'
import { postLock } from './sessionLock'

type TestResult = { ok: boolean; message: string }

type PredefinedQuery = {
  query_name: string
  query: string
  cell_view: string | null
  order_by: OrderCol[] | null
  fields: string[] | null
}

export type QueryPush = {
  query: string
  limit?: number
  offset?: number
  order_by?: OrderCol[]
  fields?: string[]
  // Raw cell-view YAML carried with this push; loaded into the editor as a
  // draft (renders immediately, persisted only when the user clicks Save).
  cell_view?: string | null
  // Predefined-query name to select in the dropdown. Selection only — the push
  // never persists; the user's Save writes the loaded SQL + cell_view under it.
  name?: string | null
}

// Sentinel value for the predefined dropdown's "new name" item.
const NEW_NAME_OPTION = '::new::'

// The query workflow page (`/queries`). The App shell owns connection state;
// this page owns the command prompt and the connect/pick-database/query UI.
function QueryView({
  connection,
  setConnection,
  pushed,
  onPushConsumed,
  remoteId,
}: {
  connection: Connection | null
  setConnection: (c: Connection | null) => void
  pushed?: QueryPush | null
  onPushConsumed?: () => void
  remoteId?: string | null
}) {
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState('')
  const [hint, setHint] = useState<string | null>(null)
  // The driver whose connection form is open, or null when no form is shown.
  const [formType, setFormType] = useState<string | null>(null)
  const [showQuery, setShowQuery] = useState(false)
  // Command-prompt autocomplete: highlighted row, and whether Esc dismissed it.
  const [acIndex, setAcIndex] = useState(0)
  const [acDismissed, setAcDismissed] = useState(false)
  const [connNames, setConnNames] = useState<string[]>([])
  const promptRef = useRef<HTMLInputElement>(null)
  // Saved queries surfaced next to the title on the landing screen, so they're
  // reachable without first typing `query`. Scoped like the panel's dropdown.
  const [landingQueries, setLandingQueries] = useState<PredefinedQuery[]>([])
  // A query synthesized from a landing pick, fed through the same `pushed` path
  // the agent uses — so the panel opens and auto-runs it, no duplicate logic.
  const [localPush, setLocalPush] = useState<QueryPush | null>(null)

  // Saved connection names power `connect <name>` autocomplete; refresh on mount
  // and whenever the set may have changed (new connection created).
  const refreshConnections = useCallback(async () => {
    try {
      const res = await fetch('/api/db/connections')
      const data = await res.json()
      setConnNames(Array.isArray(data.names) ? (data.names as string[]) : [])
    } catch {
      /* leave the last known list in place on a failed refresh */
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshConnections()
  }, [refreshConnections])

  const ready = isReady(connection)

  // Pushed query arrives via the shell's SSE listener; mount the panel to run it.
  useEffect(() => {
    if (pushed && ready) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setShowQuery(true)
    }
  }, [pushed, ready])

  // Load saved queries for the landing dropdown once a connection is ready.
  // Scoped to the connection type + active workspace, mirroring the panel. The
  // list is only shown while `ready`, so a stale set need not be cleared here.
  useEffect(() => {
    if (!ready || !connection) return
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch(
          `/api/predefined-queries?type=${encodeURIComponent(connection.type)}` +
            `&workspace=${encodeURIComponent(activeWorkspace())}`,
        )
        const data = await res.json()
        if (!cancelled) setLandingQueries((data.queries ?? []) as PredefinedQuery[])
      } catch {
        /* leave the last known list in place on a failed refresh */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [ready, connection])

  // Landing-dropdown pick: open the panel and run the chosen query by routing it
  // through the same `pushed` channel used for agent pushes.
  function pickPredefined(name: string) {
    const q = landingQueries.find((p) => p.query_name === name)
    if (!q) return
    setFormType(null)
    setHint(null)
    setShowQuery(true)
    setLocalPush({
      query: q.query,
      order_by: q.order_by ?? undefined,
      fields: q.fields ?? undefined,
      cell_view: q.cell_view,
      name: q.query_name,
    })
  }

  // Clear the local push once the panel has consumed it, then forward to the
  // shell's handler for any agent-originated push.
  const handlePushConsumed = () => {
    setLocalPush(null)
    onPushConsumed?.()
  }

  async function openSaved(name: string) {
    try {
      const res = await fetch('/api/db/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const data = await res.json()
      if (!data.ok) {
        setHint(data.message ?? `no connection named “${name}”`)
        return
      }
      setFormType(null)
      setShowQuery(false)
      setHint(null)
      setConnection({
        name: data.name,
        type: (data.type ?? 'clickhouse') as string,
        databases: (data.databases ?? []) as string[],
        database: null,
      })
      setPrompt(`connect ${data.name}`)
    } catch (err) {
      setHint(err instanceof Error ? err.message : 'request failed')
    }
  }

  function submitPrompt(e: React.FormEvent) {
    e.preventDefault()
    const raw = prompt.trim()
    if (!raw) return
    const lower = raw.toLowerCase()
    if (lower.startsWith('new ')) {
      const type = lower.slice('new '.length).trim()
      if (DRIVERS[type]) {
        setFormType(type)
        setShowQuery(false)
        setHint(null)
      } else {
        setHint(`Unknown driver “${type}”. Try: ${Object.keys(DRIVERS).join(', ')}.`)
      }
      return
    }
    if (lower === 'query') {
      if (ready) {
        setShowQuery(true)
        setFormType(null)
        setHint(null)
      } else {
        setHint('Select a database first.')
      }
      return
    }
    if (lower === 'disconnect') {
      void disconnect()
      return
    }
    if (lower === 'explorer') {
      navigate('/explorer')
      return
    }
    if (lower === 'dashboard') {
      navigate('/dashboard')
      return
    }
    if (lower.startsWith('dashboard ')) {
      const name = raw.slice('dashboard '.length).trim().split(/\s+/)[0]
      if (name) {
        navigate(`/dashboard?name=${encodeURIComponent(name)}`)
        return
      }
    }
    if (lower.startsWith('connect ')) {
      const name = raw.slice('connect '.length).trim().split(/\s+/)[0]
      if (name) {
        void openSaved(name)
        return
      }
    }
    setFormType(null)
    setShowQuery(false)
    setHint(
      `Unknown command “${raw}”. Try “new ${Object.keys(DRIVERS).join('|')}”, ` +
        `“connect <name>”, “explorer”, “dashboard <name>” or “disconnect”.`,
    )
  }

  function handleConnected(name: string, type: string, databases: string[]) {
    const opened = { name, type, databases, database: null }
    setConnection(opened)
    setFormType(null)
    setShowQuery(false)
    setPrompt(`connect ${name}`)
    void refreshConnections()
    // A picker-less driver (DuckDB) is ready the moment it connects, so it
    // goes straight to the tables; the rest stay here to pick a database.
    if (isReady(opened)) navigate('/explorer')
  }

  // Drop the active connection both server- and client-side, returning to the
  // bare command prompt. Saved connections survive — `connect <name>` reopens.
  async function disconnect() {
    try {
      await fetch('/api/db/disconnect', { method: 'POST' })
    } catch {
      /* a failed disconnect still clears the UI; the session is best-effort */
    }
    setConnection(null)
    setFormType(null)
    setShowQuery(false)
    setHint(null)
    setPrompt('')
  }

  async function selectDatabase(database: string) {
    if (!connection) return
    const res = await fetch('/api/db/database', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ database }),
    })
    if (res.ok) {
      setConnection({ ...connection, database })
      // Clear the prompt so the placeholder invites a query on the way back.
      setPrompt('')
      // The connection is live now: browse its tables (see
      // docs/queryview.md#landing-page).
      navigate('/explorer')
    }
  }

  const inQueryMode = showQuery && ready

  // Command-prompt autocomplete suggestions for the current input. Hidden when
  // dismissed, empty, or the lone match already equals what's typed.
  const suggestions = useMemo(
    () =>
      suggestCompletions(prompt, {
        drivers: Object.keys(DRIVERS),
        connections: connNames,
        ready,
        connected: !!connection,
      }),
    [prompt, ready, connection, connNames],
  )
  const showAc =
    !acDismissed &&
    prompt.trim() !== '' && // nothing typed yet → no unsolicited dropdown
    suggestions.length > 0 &&
    !(suggestions.length === 1 && suggestions[0].value === prompt)
  const acActive = Math.min(acIndex, suggestions.length - 1)

  function acceptSuggestion(s: Suggestion) {
    setPrompt(s.value)
    setAcIndex(0)
    setAcDismissed(false)
    promptRef.current?.focus()
  }

  function onPromptKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!showAc) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setAcIndex((i) => (Math.min(i, suggestions.length - 1) + 1) % suggestions.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setAcIndex(
        (i) =>
          (Math.min(i, suggestions.length - 1) - 1 + suggestions.length) % suggestions.length,
      )
    } else if (e.key === 'Tab' || e.key === 'Enter') {
      // Accept the highlighted row rather than completing/submitting.
      e.preventDefault()
      acceptSuggestion(suggestions[acActive])
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setAcDismissed(true)
    }
  }

  // Command prompt. In query mode it joins the panel's top row to save space.
  const promptInput = (
    <form
      onSubmit={submitPrompt}
      className={`relative ${inQueryMode ? 'min-w-0 flex-1' : ''}`}
    >
      <input
        ref={promptRef}
        type="text"
        value={prompt}
        onChange={(e) => {
          setPrompt(e.target.value)
          setAcIndex(0)
          setAcDismissed(false)
        }}
        onKeyDown={onPromptKeyDown}
        placeholder={ready ? 'query' : 'Type a command, e.g. new clickhouse'}
        aria-label="Prompt"
        data-testid="prompt-input"
        autoFocus
        autoComplete="off"
        role="combobox"
        aria-expanded={showAc}
        aria-controls="prompt-suggestions"
        aria-activedescendant={showAc ? `prompt-suggestion-${acActive}` : undefined}
        className={
          inQueryMode
            ? 'glass-input w-full px-3 py-2 text-sm'
            : 'glass-input w-full px-4 py-3 text-center'
        }
      />
      {showAc && (
        <ul
          id="prompt-suggestions"
          role="listbox"
          data-testid="prompt-suggestions"
          className="absolute left-0 right-0 top-full z-20 mt-1 overflow-hidden rounded-lg border border-white/10 bg-slate-900/95 text-left shadow-xl backdrop-blur"
        >
          {suggestions.map((s, i) => (
            <li
              key={s.value}
              id={`prompt-suggestion-${i}`}
              role="option"
              aria-selected={i === acActive}
              data-testid={`suggestion-${s.label}`}
              onMouseDown={(e) => {
                // Keep focus on the input; mousedown beats the input's blur.
                e.preventDefault()
                acceptSuggestion(s)
              }}
              className={`flex cursor-pointer items-baseline justify-between px-3 py-2 text-sm ${
                i === acActive ? 'bg-indigo-500/30 text-white' : 'text-slate-300 hover:bg-white/5'
              }`}
            >
              <span className="font-medium">{s.label}</span>
              <span className="ml-3 text-xs text-slate-500">{s.hint}</span>
            </li>
          ))}
        </ul>
      )}
    </form>
  )

  return (
    <div className={`w-full ${inQueryMode ? 'max-w-[80vw]' : 'max-w-md'}`}>
      <div className="mb-6 flex items-center justify-center gap-4">
        <h1 className="text-3xl font-bold tracking-tight text-white [text-shadow:0_2px_30px_rgba(129,140,248,0.45)]">
          QueryView
        </h1>
        {!inQueryMode && ready && landingQueries.length > 0 && (
          <select
            data-testid="landing-predefined-select"
            aria-label="Predefined queries"
            value=""
            onChange={(e) => {
              if (e.target.value) pickPredefined(e.target.value)
            }}
            className="glass-input px-3 py-2 text-sm"
          >
            <option value="" disabled>
              Saved queries…
            </option>
            {landingQueries.map((p) => (
              <option key={p.query_name} value={p.query_name}>
                {p.query_name}
              </option>
            ))}
          </select>
        )}
      </div>

      {!inQueryMode && promptInput}

      {hint && (
        <p className="mt-3 text-center text-sm text-slate-400" data-testid="prompt-hint">
          {hint}
        </p>
      )}

      {formType && DRIVERS[formType] && (
        <ConnectionForm meta={DRIVERS[formType]} onConnected={handleConnected} />
      )}

      {!formType && connection && connection.database === null &&
        connection.databases.length > 0 && (
          <DatabasePicker connection={connection} onSelect={selectDatabase} />
        )}

      {showQuery && ready && connection && (
        <QueryPanel
          connectionType={connection.type}
          promptSlot={promptInput}
          pushed={pushed ?? localPush}
          onPushConsumed={handlePushConsumed}
          remoteId={remoteId}
        />
      )}
    </div>
  )
}

function ConnectionForm({
  meta,
  onConnected,
}: {
  meta: DriverMeta
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
      const res = await fetch('/api/db/test', {
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
      const res = await fetch('/api/db/connect', {
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
      className="glass-panel mt-6 space-y-4 p-6"
    >
      <h2 className="text-lg font-semibold">New {meta.label} connection</h2>

      {meta.fields.map((f) => (
        <label key={f.key} className="block text-sm font-medium text-slate-300">
          {f.label}
          <input
            type={f.type}
            value={values[f.key]}
            onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
            aria-label={f.label}
            data-testid={f.testid}
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

function DatabasePicker({
  connection,
  onSelect,
}: {
  connection: Connection
  onSelect: (database: string) => void
}) {
  const [filter, setFilter] = useState('')
  const visible = useMemo(
    () => filterDatabases(connection.databases, filter),
    [connection.databases, filter],
  )
  return (
    // Wider than the landing column (which stays prompt-sized) so long
    // database names fit several per row; centred by shifting half its width.
    <section
      data-testid="db-picker"
      className="glass-panel relative left-1/2 mt-6 w-[min(48rem,calc(100vw-2rem))] -translate-x-1/2 p-6"
    >
      <h2 className="text-sm font-medium text-slate-200">
        Connected to {connection.name}. Select a database:
      </h2>
      <form
        className="mt-3"
        onSubmit={(e) => {
          // Enter picks the first match so a typed prefix is enough to connect.
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
        {visible.map((db) => {
          const selected = db === connection.database
          return (
            <button
              key={db}
              type="button"
              onClick={() => onSelect(db)}
              data-testid="db-option"
              data-db={db}
              className={`glass-toggle px-3 py-1.5 text-sm ${selected ? 'is-active' : ''}`}
            >
              {db}
            </button>
          )
        })}
      </div>
    </section>
  )
}

// First column of each result row, as text — the dropdown options for an
// `options_sql` param. An empty result yields [].
function firstColumn(rows: QueryRows): string[] {
  return rows.data.map((r) => cellText(r[0]))
}

function QueryPanel({
  connectionType,
  promptSlot,
  pushed,
  onPushConsumed,
  remoteId,
}: {
  connectionType: string
  promptSlot?: React.ReactNode
  pushed?: QueryPush | null
  onPushConsumed?: () => void
  remoteId?: string | null
}) {
  const [sql, setSql] = useState('')
  const [limit, setLimit] = useState(100)
  const [offset, setOffset] = useState(0)
  const [rows, setRows] = useState(4)
  const [result, setResult] = useState<QueryRows | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [predefined, setPredefined] = useState<PredefinedQuery[]>([])
  const [selectedName, setSelectedName] = useState('')
  const [fields, setFields] = useState<Field[]>([])
  const [visibleCols, setVisibleCols] = useState<string[]>([])
  // Column → type from the result's own metadata. Drives the built-in default
  // views; independent of the Fields picker so it never resets the user's
  // column selection.
  const colTypes = useMemo(() => (result ? columnTypes(result) : {}), [result])
  const [orderBy, setOrderBy] = useState<OrderCol[]>([])
  const [cellViewModalOpen, setCellViewModalOpen] = useState(false)
  // Transient "Copied" feedback for the copy-name button.
  const [copiedName, setCopiedName] = useState(false)
  // Panel root, for the edit-lock focus tracker.
  const panelRef = useRef<HTMLElement>(null)
  const blurTimer = useRef<number | undefined>(undefined)

  // Edit lock: acquire on panel focus (+ ~10s heartbeat to refresh the 30s TTL),
  // release on blur out of the panel. Advisory — postLock swallows errors.
  useEffect(() => {
    const el = panelRef.current
    if (!el || !remoteId) return
    const acquire = () => void postLock(remoteId, 'acquire')
    const onFocusIn = () => {
      window.clearTimeout(blurTimer.current)
      acquire()
    }
    const onFocusOut = () => {
      // Debounce: moving between inputs fires focusout then focusin.
      window.clearTimeout(blurTimer.current)
      blurTimer.current = window.setTimeout(() => {
        if (!el.contains(document.activeElement)) void postLock(remoteId, 'release')
      }, 150)
    }
    el.addEventListener('focusin', onFocusIn)
    el.addEventListener('focusout', onFocusOut)
    const beat = window.setInterval(() => {
      if (el.contains(document.activeElement)) acquire()
    }, 10000)
    return () => {
      el.removeEventListener('focusin', onFocusIn)
      el.removeEventListener('focusout', onFocusOut)
      window.clearInterval(beat)
      window.clearTimeout(blurTimer.current)
    }
  }, [remoteId])
  // Cell-view YAML carried by a push, loaded as an unsaved draft: it renders
  // and seeds the editor/Save, but isn't persisted until the user clicks Save.
  // Cleared on a successful Save (the saved view takes over) or when another
  // query is picked from the dropdown. null when no push draft is active.
  const [pushedCellView, setPushedCellView] = useState<string | null>(null)

  // Saved cell_view of the selected query, or '' when none.
  const savedCellView = useMemo(
    () => predefined.find((p) => p.query_name === selectedName)?.cell_view ?? '',
    [predefined, selectedName],
  )

  // What rendering, the modal editor, and Save all read: a pushed draft wins
  // over the persisted view until it's saved or discarded.
  const effectiveCellView = pushedCellView ?? savedCellView

  // Editor edits don't take effect until Save (which refreshes `predefined`).
  const appliedViews = useMemo<CellViewMap>(
    () => parseCellViewYaml(effectiveCellView),
    [effectiveCellView],
  )

  // Selectors from the cell_view YAML's `params:` section. Each renders a
  // <select> whose value is substituted into the SQL via {name}; `options_sql`
  // choices are resolved by querying (below).
  const paramSpecs = useMemo<ParamSpec[]>(
    () => parseQueryParams(savedCellView),
    [savedCellView],
  )
  const [paramValues, setParamValues] = useState<Record<string, string>>({})
  // Resolved choices for `options_sql` params, keyed by name. An error (already
  // param-prefixed) blocks the main query.
  const [sqlOptions, setSqlOptions] = useState<Record<string, string[]>>({})
  const [optionsError, setOptionsError] = useState<string | null>(null)

  // Resolve every `options_sql` param's choices via the panel's query endpoint;
  // cached until the specs change. A failed/empty result records a blocking error.
  useEffect(() => {
    const sqlSpecs = paramSpecs.filter((s) => s.optionsSql)
    if (sqlSpecs.length === 0) {
      /* eslint-disable react-hooks/set-state-in-effect */
      setSqlOptions({})
      setOptionsError(null)
      /* eslint-enable react-hooks/set-state-in-effect */
      return
    }
    let cancelled = false
    void (async () => {
      // Fetch concurrently. Each resolves to values or a (param-prefixed) error;
      // the first failing spec in spec order blocks the query (deterministic message).
      const outcomes = await Promise.all(
        sqlSpecs.map(async (s) => {
          try {
            const res = await fetch('/api/db/query', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ query: s.optionsSql }),
            })
            const data = await res.json()
            if (!data.ok) return { name: s.name, error: data.message ?? 'query failed' }
            const values = firstColumn(data as QueryRows)
            if (values.length === 0) return { name: s.name, error: 'query returned no rows' }
            return { name: s.name, values }
          } catch (e) {
            return { name: s.name, error: e instanceof Error ? e.message : 'request failed' }
          }
        }),
      )
      if (cancelled) return
      const resolved: Record<string, string[]> = {}
      let err: string | null = null
      for (const o of outcomes) {
        if ('error' in o) {
          err = `options for "${o.name}": ${o.error}`
          break
        }
        resolved[o.name] = o.values
      }
      setSqlOptions(resolved)
      setOptionsError(err)
    })()
    return () => {
      cancelled = true
    }
  }, [paramSpecs])

  // Specs with choices resolved to a concrete list: static `options` pass
  // through; `options_sql` params take fetched values (empty until ready).
  const paramDefs = useMemo<ParamDef[]>(
    () =>
      paramSpecs.map((s) => ({
        name: s.name,
        options: s.optionsSql ? (sqlOptions[s.name] ?? []) : (s.options ?? []),
      })),
    [paramSpecs, sqlOptions],
  )

  // Block the query until every `options_sql` param resolves to a non-empty list
  // with no error. Vacuously true with no such params.
  const optionsReady =
    optionsError === null &&
    paramSpecs.every((s) => !s.optionsSql || (sqlOptions[s.name]?.length ?? 0) > 0)

  // An options_sql failure takes precedence over a run-time query error in the banner.
  const displayError = optionsError ?? error

  // Seed each param to its first option, preserving a still-valid selection.
  // Re-runs when the resolved defs change, without clobbering live picks.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setParamValues((prev) => {
      const next: Record<string, string> = {}
      for (const d of paramDefs) {
        next[d.name] = d.options.includes(prev[d.name]) ? prev[d.name] : d.options[0]
      }
      return next
    })
  }, [paramDefs])

  // Returns the fetched list (not just the state setter) so a caller that needs
  // the fresh rows right away — e.g. re-seeding the editor after a git restore —
  // doesn't have to wait a render for `predefined` state to catch up.
  const loadPredefined = useCallback(async (): Promise<PredefinedQuery[]> => {
    try {
      const res = await fetch(
        `/api/predefined-queries?type=${encodeURIComponent(connectionType)}&workspace=${encodeURIComponent(activeWorkspace())}`,
      )
      const data = await res.json()
      const list = (data.queries ?? []) as PredefinedQuery[]
      setPredefined(list)
      return list
    } catch {
      // missing list is non-fatal; leave the selector empty
      return []
    }
  }, [connectionType])

  useEffect(() => {
    // setPredefined runs after the fetch await, so it doesn't cascade renders.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadPredefined()
  }, [loadPredefined])

  // Apply a pushed query: reflect it in the controls and run it with the pushed
  // values directly (not state, which hasn't settled).
  useEffect(() => {
    if (!pushed) return
    // Don't fire while a param's options_sql is unresolved — substitution would
    // be wrong, so drop the push rather than run against bad params.
    if (!optionsReady) return
    const q = pushed.query
    const lim = pushed.limit ?? 100
    const off = pushed.offset ?? 0
    const ord = pushed.order_by ?? []
    const fld = pushed.fields ?? []
    /* eslint-disable react-hooks/set-state-in-effect */
    setSql(q)
    setLimit(lim)
    setOffset(off)
    setOrderBy(ord)
    setPushedCellView(pushed.cell_view ?? null)
    // Load everything into the editor: select the named query so the dropdown,
    // saved view, and Save all target it (selection only — nothing persisted).
    if (pushed.name != null) setSelectedName(pushed.name)
    /* eslint-enable react-hooks/set-state-in-effect */
    void runWith(q, lim, off, ord, fld)
    // Consume the push so re-mounting doesn't re-run a stale query.
    onPushConsumed?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pushed])

  async function describe() {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch('/api/db/describe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: applyParams(sql, paramDefs, paramValues) }),
      })
      const data = await res.json()
      if (data.ok) {
        const next = (data.fields ?? []) as Field[]
        setFields(next)
        // Default to all columns visible; drop stale order-by entries.
        setVisibleCols(next.map((f) => f.name))
        setOrderBy((prev) => prev.filter((o) => next.some((f) => f.name === o.name)))
      } else {
        setError(data.message ?? 'describe failed')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'request failed')
    } finally {
      setBusy(false)
    }
  }

  async function runWith(
    q: string,
    lim: number,
    off: number,
    ord: OrderCol[],
    selectFields?: string[],
    paramOverride?: Record<string, string>,
  ) {
    setBusy(true)
    setError(null)
    try {
      // Substitute {name} placeholders from the param dropdowns. An override is
      // passed when a dropdown change triggers the run (its setState hasn't committed).
      const query = applyParams(q, paramDefs, paramOverride ?? paramValues)
      const res = await fetch('/api/db/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, limit: lim, offset: off, order_by: ord }),
      })
      const data = await res.json()
      if (data.ok) {
        const rows: QueryRows = { meta: data.meta ?? [], data: data.data ?? [] }
        setResult(rows)
        setOffset(off)
        // A pushed selection is authoritative: synthesize the field list from the
        // result columns so the visibility filter restricts the table to exactly
        // the pushed columns (empty/absent => show all).
        if (selectFields !== undefined) {
          const cols = columnNames(rows)
          setFields(cols.map((name) => ({ name, type: '' })))
          setVisibleCols(
            selectFields.length ? selectFields.filter((f) => cols.includes(f)) : cols,
          )
        }
      } else {
        setError(data.message ?? 'query failed')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'request failed')
    } finally {
      setBusy(false)
    }
  }

  function run(nextOffset: number) {
    // Keep any pushed draft (cell view) across re-runs/paging so the user can
    // review and Save it; it's only cleared on Save or a dropdown selection.
    void runWith(sql, limit, nextOffset, orderBy)
  }

  async function downloadCsv() {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch('/api/db/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: applyParams(sql, paramDefs, paramValues),
          limit,
          offset,
          format: 'csv',
          order_by: orderBy,
        }),
      })
      const data = await res.json()
      if (!data.ok) {
        setError(data.message ?? 'query failed')
        return
      }
      downloadText('query.csv', data.output as string, 'text/csv')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'request failed')
    } finally {
      setBusy(false)
    }
  }

  // Dropdown selection: a saved query loads its SQL and cell_view; the "new name"
  // item prompts for a fresh name. The chosen name is what Save writes under.
  // Copy the selected predefined-query name to the clipboard, with a brief
  // "Copied" confirmation on the button.
  async function copyName() {
    const name = selectedName.trim()
    if (!name) return
    try {
      await navigator.clipboard.writeText(name)
      setCopiedName(true)
      window.setTimeout(() => setCopiedName(false), 1500)
    } catch {
      /* clipboard blocked (e.g. insecure context); silently no-op */
    }
  }

  // Load a predefined query's SQL/presentation into the editor.
  function applyPredefined(q: PredefinedQuery) {
    setSql(q.query)
    setOrderBy(q.order_by ?? [])
    setVisibleCols(q.fields ?? []) // [] = show all (matches pushed-fields semantics)
  }

  function onSelectName(value: string) {
    if (value === NEW_NAME_OPTION) {
      const name = window.prompt('Save query as (name):', selectedName || '')?.trim()
      if (name) setSelectedName(name)
      return
    }
    setSelectedName(value)
    setPushedCellView(null) // selecting a query reverts to its saved cell view
    const q = predefined.find((p) => p.query_name === value)
    if (q) applyPredefined(q)
  }

  // After a git restore overwrites the stored row, refetch the list and
  // re-seed the editor from the (now-current) row for the selected name —
  // using the freshly-fetched list directly rather than the `predefined`
  // state, which wouldn't have caught up yet.
  async function onQueryRestored() {
    const list = await loadPredefined()
    const q = list.find((p) => p.query_name === selectedName)
    if (q) applyPredefined(q)
  }

  // SQL-only saves (top button) re-persist the existing cell_view; the modal
  // passes its draft. Returns success so the modal closes only on a clean persist.
  async function save(cellViewValue: string = effectiveCellView): Promise<boolean> {
    const name = selectedName.trim()
    if (!name) return false
    setBusy(true)
    setError(null)
    try {
      const res = await fetch('/api/predefined-queries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query_name: name,
          type: connectionType,
          query: sql,
          cell_view: cellViewValue,
          workspace: activeWorkspace(),
          ...presentationForSave(orderBy, visibleCols),
        }),
      })
      const data = await res.json()
      if (data.ok) {
        // Persisted: drop the draft so the freshly-saved view takes over.
        setPushedCellView(null)
        await loadPredefined()
        return true
      }
      setError(data.message ?? 'save failed')
      return false
    } catch (err) {
      setError(err instanceof Error ? err.message : 'request failed')
      return false
    } finally {
      setBusy(false)
    }
  }

  // Modal owns its draft state (seeded from effectiveCellView, so a pushed
  // draft is editable); we just toggle visibility and forward the saved value.
  async function onCellViewSave(value: string) {
    if (await save(value)) setCellViewModalOpen(false)
  }

  const columns = result ? columnNames(result) : []
  const resultRows = result ? result.data : []
  const shownIdx = shownColumnIndices(columns, fields, visibleCols)

  const sizes: [string, number, string][] = [
    ['Min', 0, 'query-size-min'],
    ['S', 4, 'query-size-s'],
    ['M', 8, 'query-size-m'],
    ['L', 16, 'query-size-l'],
    ['XL', 28, 'query-size-xl'],
  ]
  const inputClass = 'glass-input px-3 py-2'

  return (
    <section
      ref={panelRef}
      data-testid="query-panel"
      className="glass-panel mt-6 space-y-3 p-6"
    >
      <div className="flex items-center gap-2">
        {promptSlot}
        <select
          data-testid="query-predefined-select"
          aria-label="Predefined queries"
          value={selectedName}
          onChange={(e) => onSelectName(e.target.value)}
          className={`min-w-0 flex-1 ${inputClass}`}
        >
          <option value="">Predefined queries…</option>
          <option value={NEW_NAME_OPTION}>+ New name…</option>
          {selectedName !== '' &&
            !predefined.some((p) => p.query_name === selectedName) && (
              <option value={selectedName}>{selectedName}</option>
            )}
          {predefined.map((p) => (
            <option key={p.query_name} value={p.query_name}>
              {p.query_name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void copyName()}
          disabled={!selectedName.trim()}
          data-testid="query-copy-name"
          title="Copy query name"
          aria-label="Copy query name"
          className="glass-btn min-w-[4.5rem] px-3 py-2 text-center font-medium"
        >
          {copiedName ? 'Copied' : 'Copy'}
        </button>
        <button
          type="button"
          onClick={() => void save()}
          disabled={busy || !selectedName.trim()}
          data-testid="query-save"
          className="glass-btn px-3 py-2 font-medium"
        >
          Save
        </button>
        <GitSyncControls
          kind="query"
          name={selectedName}
          connType={connectionType}
          disabled={busy || !selectedName.trim()}
          onRestored={() => void onQueryRestored()}
        />
        <ExportImportControls
          kind="query"
          name={selectedName}
          connType={connectionType}
          disabled={busy}
          onImported={() => void onQueryRestored()}
        />
      </div>

      {paramDefs.length > 0 && (
        <div
          data-testid="query-params"
          className="flex flex-wrap items-center gap-x-4 gap-y-2"
        >
          {paramDefs.map((def) => (
            <label
              key={def.name}
              className="flex items-center gap-1.5 text-sm text-slate-300"
            >
              {def.name}
              <select
                data-testid="param-select"
                data-param={def.name}
                aria-label={`Parameter ${def.name}`}
                value={paramValues[def.name] ?? def.options[0]}
                onChange={(e) => {
                  const next = { ...paramValues, [def.name]: e.target.value }
                  setParamValues(next)
                  // Pass new values directly: setParamValues hasn't committed.
                  // runWith resets offset to 0 when the query succeeds.
                  if (optionsReady) void runWith(sql, limit, 0, orderBy, undefined, next)
                }}
                className={inputClass}
              >
                {def.options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}

      <div className="flex justify-end gap-1">
        <button
          type="button"
          onClick={() => setCellViewModalOpen(true)}
          data-testid="cell-view-toggle"
          className="glass-toggle mr-2 px-2 py-1 text-xs"
        >
          Cell view
        </button>
        {sizes.map(([label, n, testid]) => (
          <button
            key={testid}
            type="button"
            onClick={() => setRows(n)}
            data-testid={testid}
            className={`glass-toggle px-2 py-1 text-xs ${rows === n ? 'is-active' : ''}`}
          >
            {label}
          </button>
        ))}
      </div>

      <textarea
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        aria-label="SQL query"
        data-testid="query-input"
        rows={rows || 1}
        placeholder="SELECT …"
        className={`glass-input w-full px-3 font-mono text-sm ${
          rows === 0 ? 'h-0 min-h-0 overflow-hidden border-transparent py-0' : 'py-2'
        }`}
      />

      {cellViewModalOpen && (
        <CellViewModal
          initial={effectiveCellView}
          onCancel={() => setCellViewModalOpen(false)}
          onSave={(value) => void onCellViewSave(value)}
          saveDisabled={busy || !selectedName.trim()}
        />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void run(offset)}
          disabled={busy || !optionsReady}
          data-testid="query-run"
          className="glass-btn-primary px-4 py-2 font-medium"
        >
          Execute
        </button>
        <button
          type="button"
          onClick={() => void describe()}
          disabled={busy || !optionsReady}
          data-testid="query-fields"
          className={`px-3 py-2 text-sm font-medium ${
            fields.length > 0 ? 'glass-btn-primary' : 'glass-btn'
          }`}
        >
          Fields
        </button>
        <label className="text-sm text-slate-300">
          Limit
          <input
            type="number"
            value={limit}
            min={1}
            onChange={(e) => setLimit(Number(e.target.value) || 1)}
            aria-label="Limit"
            data-testid="query-limit"
            className={`ml-1 w-20 ${inputClass}`}
          />
        </label>
        <label className="text-sm text-slate-300">
          Offset
          <input
            type="number"
            value={offset}
            min={0}
            onChange={(e) => setOffset(Number(e.target.value) || 0)}
            aria-label="Offset"
            data-testid="query-offset"
            className={`ml-1 w-20 ${inputClass}`}
          />
        </label>
        <button
          type="button"
          onClick={() => void run(Math.max(0, offset - limit))}
          disabled={busy || !optionsReady || offset === 0}
          data-testid="query-prev"
          className="glass-btn px-3 py-2 text-sm"
        >
          ← Previous
        </button>
        <button
          type="button"
          onClick={() => void run(offset + limit)}
          disabled={busy || !optionsReady}
          data-testid="query-next"
          className="glass-btn px-3 py-2 text-sm"
        >
          Next →
        </button>
        <button
          type="button"
          onClick={downloadCsv}
          disabled={busy || !optionsReady}
          data-testid="query-csv"
          className="glass-btn px-3 py-2 text-sm font-medium text-emerald-300"
        >
          Download CSV
        </button>
      </div>

      {fields.length > 0 && (
        <FieldPickers
          fields={fields}
          visibleCols={visibleCols}
          orderBy={orderBy}
          onVisibleColsChange={setVisibleCols}
          onOrderByChange={setOrderBy}
          orderHeaderExtra={
            <>
              <button
                type="button"
                data-testid="orderby-run"
                onClick={() => void run(offset)}
                disabled={busy}
                className="glass-btn px-2 py-0.5 text-xs font-medium text-indigo-200"
              >
                Run
              </button>
              <span className="text-xs text-slate-400">(re-runs the query)</span>
            </>
          }
        />
      )}

      {result !== null && (
        <ResultsTable
          columns={columns}
          rows={resultRows}
          shownIdx={shownIdx}
          testid="query-output"
          renderCell={(col, value, row) =>
            renderCell(col, value, appliedViews, row, columns, colTypes)
          }
        />
      )}
      {displayError && (
        <p data-testid="query-error" className="text-sm text-red-300">
          {displayError}
        </p>
      )}
    </section>
  )
}

export default QueryView
