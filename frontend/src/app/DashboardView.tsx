import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'

import {
  DashboardFrame,
  applyToQueries,
  parseDashboardParams,
  parseParamsRequest,
  parseWidgetRequest,
  rejectedWidgetReply,
  resolveParams,
  widgetQueryNames,
  type DashboardParam,
  type Dialect,
  type DashboardResults,
  type QueryRunner,
  type ResolvedParam,
} from '../core'
import ExportImportControls from './controls/ExportImportControls'
import GitSyncControls from './controls/GitSyncControls'
import { apiFetch, postJson } from './api'
import DashboardSqlPanel from './DashboardSqlPanel'
import { onGitSync } from './gitsync'
import { activeWorkspace, patchView, viewState } from './session'
import { answerWidget, type WidgetSql } from './widgetHost'

// A dashboard names no connection: it runs on the viewing session's.
export type DashboardPush = {
  name: string
  html: string
  queries: Record<string, string>
  // Selector specs (docs/dashboard.md, "Dashboard parameters").
  params?: unknown[]
}

type DashboardSummary = { name: string; updated_at: number }

// Not connected / no database: say what to do, not what went wrong.
function runError(data: { reason?: string; message?: string }): string {
  if (data.reason === 'no-session') return 'Connect to a database to run this dashboard.'
  if (data.reason === 'no-database') return 'Select a database to run this dashboard.'
  return data.message ?? 'Failed to run queries.'
}

// Run named SQL on the session's connection; shared by the load, the params'
// options_sql, and set-params re-runs.
const runQueries: QueryRunner = async (queries) => {
  try {
    const res = await postJson('/api/runqueries', { queries })
    const data = await res.json().catch(() => ({}))
    if (!res.ok || !data.ok) return { ok: false, message: runError(data) }
    return { ok: true, results: (data.results ?? {}) as DashboardResults }
  } catch {
    return { ok: false, message: 'Failed to run queries.' }
  }
}

// The frame paints its own backdrop; match the app's instead of white.
const NEW_QUERY_HTML =
  '<style>body{margin:0;background:#0c1124}</style>' +
  '<qv-select-view query="main"></qv-select-view>'

// The session view holding the unsaved New query draft, so it survives leaving
// the page and a reload (docs/session.md).
const VIEW = 'dashboard'

// The draft the session remembers, when the page opens without a dashboard.
function restoredDraft(params: URLSearchParams): DashboardPush | null {
  if (params.has('name') || params.has('new')) return null
  const d = viewState(VIEW).draft as { html?: unknown; queries?: unknown } | null | undefined
  if (!d || typeof d.html !== 'string' || !d.queries || typeof d.queries !== 'object') return null
  return { name: '', html: d.html, queries: d.queries as Record<string, string>, params: [] }
}

// A query a <qv-select-view> names is the widget's alone: it runs per widget,
// paged, so it is left out of the up-front run and of `window.queries`.
function withoutWidgetQueries(
  queries: Record<string, string>,
  html: string,
): Record<string, string> {
  const owned = new Set(widgetQueryNames(html))
  return Object.fromEntries(Object.entries(queries).filter(([name]) => !owned.has(name)))
}

// Run a dashboard's own (non-widget) queries with the selections applied. A
// query still waiting on an unchosen selector (`default: none`) is held back;
// the page gets it once it calls setParams.
async function runOwnQueries(
  queries: Record<string, string>,
  html: string,
  declared: DashboardParam[],
  resolved: ResolvedParam[],
  dialect: Dialect,
): ReturnType<QueryRunner> {
  const runnable = applyToQueries(withoutWidgetQueries(queries, html), declared, resolved, dialect)
  return Object.keys(runnable).length ? runQueries(runnable) : { ok: true, results: {} }
}

// The dashboard page (`/dashboard?name=x`). Picks a saved dashboard (dropdown or
// `?name=`), resolves its params, runs its queries via /api/runqueries on the
// session's connection and selected database, and renders the agent HTML in a
// sandboxed iframe with results as `window.queries` and selectors as
// `window.params`. A pushed dashboard renders without a refetch.
function DashboardView({
  pushed,
  onPushConsumed,
  runOn,
  identQuote = '"',
  backslashEscapes = false,
  remoteId = null,
}: {
  pushed?: DashboardPush | null
  onPushConsumed?: () => void
  // The session's connection and database; a change re-runs the queries.
  runOn?: string | null
  // The connection's identifier quote, for `identifier` params.
  identQuote?: string
  // Whether backslash escapes in the connection's dialect.
  backslashEscapes?: boolean
  // The armed remote session, for the SQL panel's edit lock.
  remoteId?: string | null
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  // How the connection quotes identifiers and string literals.
  const dialect = useMemo<Dialect>(
    () => ({ quote: identQuote, backslashEscapes }),
    [identQuote, backslashEscapes],
  )
  const name = searchParams.get('name') ?? ''

  const [dashboards, setDashboards] = useState<DashboardSummary[]>([])
  // Captured locally so consuming the shell push doesn't re-trigger resolve.
  const [localPush, setLocalPush] = useState<DashboardPush | null>(() =>
    restoredDraft(searchParams),
  )
  const [active, setActive] = useState<DashboardPush | null>(null)
  const [results, setResults] = useState<DashboardResults | null>(null)
  // Resolved selectors at load; later changes live in the frame (window.params).
  const [params, setParams] = useState<ResolvedParam[]>([])
  // The selectors as last resolved (load or set-params): what a widget's
  // query is substituted with.
  const resolvedRef = useRef<ResolvedParam[]>([])
  const frameRef = useRef<HTMLIFrameElement>(null)
  // The SQL as last run (load or Execute). The frame's widgets and param
  // re-runs use this, so a half-typed edit in the SQL panel never runs.
  const executedRef = useRef<Record<string, string>>({})
  // The page-query results the frame holds as `window.queries`.
  const shownRef = useRef<DashboardResults>({})
  // The open dashboard with unsaved SQL-panel edits, or null.
  const editedRef = useRef<DashboardPush | null>(null)
  const [showSql, setShowSql] = useState(() => localPush !== null)
  // Bumped per load, keying the frame: a draft reloads from memory with the
  // same HTML and results, which alone would leave the old frame (and its
  // widgets' rows from the previous database) in place.
  const [loadSeq, setLoadSeq] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  // Bumped after a git restore to re-trigger the load effect below without
  // otherwise changing its dependencies.
  const [reloadNonce, setReloadNonce] = useState(0)

  // Refetch the dropdown list (also used after a Save to surface a new name).
  async function loadDashboards() {
    try {
      const d = await (
        await apiFetch(`/api/dashboards?workspace=${encodeURIComponent(activeWorkspace())}`)
      ).json()
      setDashboards((d.dashboards ?? []) as DashboardSummary[])
    } catch {
      /* non-fatal; keep the last list */
    }
  }

  // User-only persist: an agent push renders a draft; this Save writes the
  // currently-active dashboard (draft or loaded) to the store.
  async function save() {
    if (!active) return
    // An agent's new draft arrives unnamed: naming it is the user's.
    const saveAs = active.name || window.prompt('Save dashboard as (name):')?.trim()
    if (!saveAs) return
    if (!active.name && dashboards.some((d) => d.name === saveAs)) {
      setError(`A dashboard named “${saveAs}” already exists.`)
      return
    }
    setSaving(true)
    setError(null)
    try {
      const res = await postJson('/api/dashboards', {
        name: saveAs,
        html: active.html,
        queries: active.queries,
        params: active.params ?? [],
        workspace: activeWorkspace(),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || !data.ok) {
        setError(data.message ?? 'Failed to save dashboard.')
        return
      }
      await loadDashboards()
      if (!active.name) {
        // Same object in both: the reload under the new name keeps running
        // the SQL as last executed, not an unexecuted edit just saved.
        const saved = { ...active, name: saveAs }
        editedRef.current = saved
        setLocalPush(saved)
        patchView(VIEW, { draft: null })
        setSearchParams({ name: saveAs })
      }
    } catch {
      setError('Failed to save dashboard.')
    } finally {
      setSaving(false)
    }
  }

  // `/dashboard?new` opens a New query draft: where /studio redirects, and how
  // the Scripts page hands over its last statement (as router state).
  const location = useLocation()
  useEffect(() => {
    if (!searchParams.has('new')) return
    const sql = (location.state as { sql?: unknown } | null)?.sql
    newQuery(typeof sql === 'string' ? sql : '', true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  // A git sync may have imported dashboards from the repo.
  useEffect(() => onGitSync(() => void loadDashboards()), [])

  // Load the dropdown list; refresh on each push so a new dashboard appears.
  useEffect(() => {
    let cancelled = false
    apiFetch(`/api/dashboards?workspace=${encodeURIComponent(activeWorkspace())}`)
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled) setDashboards((d.dashboards ?? []) as DashboardSummary[])
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [pushed])

  // Capture a pushed dashboard and release it from the shell.
  useEffect(() => {
    if (pushed) {
      reopen(pushed)
      onPushConsumed?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pushed])

  // Resolve the selected dashboard (pushed payload if it matches, else the store),
  // then run its queries. Fail-fast: a non-2xx /api/runqueries response surfaces
  // as a dashboard-level error and renders no iframe.
  useEffect(() => {
    let cancelled = false

    // The selected dashboard; returns null (and sets an error) if it can't load.
    async function loadDashboard(): Promise<DashboardPush | null> {
      // Edits belong to the dashboard they were made on.
      if (editedRef.current && editedRef.current.name !== name) editedRef.current = null
      if (editedRef.current) return editedRef.current
      if (localPush && localPush.name === name) return localPush
      try {
        const res = await fetch(
          `/api/dashboards/${encodeURIComponent(name)}?workspace=${encodeURIComponent(activeWorkspace())}`,
        )
        if (!res.ok) {
          if (!cancelled) setError(`Dashboard “${name}” not found.`)
          return null
        }
        return (await res.json()) as DashboardPush
      } catch {
        if (!cancelled) setError('Failed to load dashboard.')
        return null
      }
    }

    async function resolve() {
      setError(null)
      setResults(null)
      setActive(null)
      if (!name && localPush?.name !== '') return

      const dash = await loadDashboard()
      if (cancelled || !dash) return
      setActive(dash)
      // A reload with unexecuted edits (a database switch) keeps them in the
      // editor and re-runs the SQL as last executed.
      if (dash !== editedRef.current) executedRef.current = dash.queries
      const executed = executedRef.current

      setLoading(true)
      try {
        const declared = parseDashboardParams(dash.params)
        const resolved = await resolveParams(declared, {}, runQueries, dialect)
        if (cancelled) return
        setParams(resolved)
        resolvedRef.current = resolved
        const r = await runOwnQueries(executed, dash.html, declared, resolved, dialect)
        if (cancelled) return
        if (r.ok) {
          setResults(r.results)
          shownRef.current = r.results
          setLoadSeq((n) => n + 1)
        } else setError(r.message)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to run queries.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void resolve()
    return () => {
      cancelled = true
    }
  }, [name, localPush, runOn, reloadNonce, dialect])

  // Re-run the open dashboard's own queries, as last executed, and build the
  // message the frame expects. `values` are fresh selections to resolve; null
  // keeps the current ones (the SQL changed, not the params).
  // `only` limits the run to those queries (the ones Execute changed); the
  // frame keeps the rest, and only widgets over those re-query.
  async function rerun(
    dash: DashboardPush,
    values: Record<string, string> | null,
    only: string[] | null = null,
  ): Promise<Record<string, unknown>> {
    const declared = parseDashboardParams(dash.params)
    let resolved = resolvedRef.current
    try {
      if (values) {
        resolved = await resolveParams(declared, values, runQueries, dialect)
        resolvedRef.current = resolved
      }
      const executed = executedRef.current
      const queries = only ? Object.fromEntries(only.map((n) => [n, executed[n]])) : executed
      const r = await runOwnQueries(queries, dash.html, declared, resolved, dialect)
      if (!r.ok) return { type: 'params-results', ok: false, message: r.message, params: resolved }
      // window.queries is replaced whole: keep what this run left alone.
      shownRef.current = only ? { ...shownRef.current, ...r.results } : r.results
      return {
        type: 'params-results',
        ok: true,
        results: shownRef.current,
        params: resolved,
        queries: only,
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to run queries.'
      return { type: 'params-results', ok: false, message, params: [] }
    }
  }

  // An edit in the SQL panel. Kept in a ref too, so a reload (a database
  // switch) keeps it in the editor; nothing runs it until Execute.
  function editQuery(query: string, sql: string) {
    if (!active) return
    const next = { ...active, queries: { ...active.queries, [query]: sql } }
    editedRef.current = next
    setActive(next)
    // Queued; written when the SQL panel is left (its edit lock flushes).
    if (!next.name) patchView(VIEW, { draft: { html: next.html, queries: next.queries } })
  }

  // Execute from the SQL panel: post into the live frame rather than rebuild
  // it, so the page keeps its state; its widgets re-query on the same message.
  async function execute() {
    if (!active) return
    const before = executedRef.current
    const changed = Object.keys(active.queries).filter((n) => active.queries[n] !== before[n])
    executedRef.current = active.queries
    const frame = frameRef.current
    if (!frame) {
      setReloadNonce((n) => n + 1)
      return
    }
    // Nothing edited: Execute refreshes everything.
    const answer = await rerun(active, null, changed.length ? changed : null)
    // The page keeps its last results; the failure shows above it.
    setError(answer.ok ? null : String(answer.message))
    frame.contentWindow?.postMessage(answer, '*')
  }

  // Open `push` in place of the current dashboard (null: the store's copy of
  // the selected one), dropping unsaved edits and the remembered draft.
  function reopen(push: DashboardPush | null) {
    editedRef.current = null
    setLocalPush(push)
  }

  // Unsaved scratch: one widget over one query, the SQL panel open.
  function newQuery(sql = '', replace = false) {
    reopen({
      name: '',
      html: NEW_QUERY_HTML,
      queries: { main: sql },
      params: [],
    })
    patchView(VIEW, { draft: { html: NEW_QUERY_HTML, queries: { main: sql } } })
    // From `?new`, replace it: Back must not land on it and reset the draft.
    setSearchParams({}, { replace })
    setShowSql(true)
  }

  // Answer the page's setParams: values only, and only from this dashboard's
  // own frame. The SQL is the dashboard's, substituted here, so the page never
  // issues SQL of its own.
  useEffect(() => {
    if (!active) return
    const declared = parseDashboardParams(active.params)
    // One of this dashboard's queries, with the current selections applied.
    function sqlFor(query: string): WidgetSql {
      // hasOwn: a name like `constructor` must not find Object's own.
      if (!Object.hasOwn(executedRef.current, query)) return { message: `Unknown query “${query}”` }
      const sql = executedRef.current[query]
      if (!sql.trim()) return { message: 'Enter a query.' }
      const applied = applyToQueries({ [query]: sql }, declared, resolvedRef.current, dialect)
      return query in applied
        ? { sql: applied[query] }
        : { message: 'Waiting for a parameter choice.' }
    }
    async function onMessage(e: MessageEvent) {
      const frame = frameRef.current
      if (!frame || e.source !== frame.contentWindow) return
      if (!active) return
      const widget = parseWidgetRequest(e.data)
      if (widget) {
        const reply = await answerWidget(widget, sqlFor, setError)
        if (reply) frame.contentWindow?.postMessage(reply, '*')
        return
      }
      const rejected = rejectedWidgetReply(e.data)
      if (rejected) {
        frame.contentWindow?.postMessage(rejected, '*')
        return
      }
      const values = parseParamsRequest(e.data)
      if (!values) return
      const answer = await rerun(active, values)
      frame.contentWindow?.postMessage(answer, '*')
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
    // rerun reads only refs and the dialect beyond its arguments.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, dialect])

  return (
    // mt clears the floating header when the page is taller than the window.
    <div className="mt-10 w-full" data-testid="dashboard-view">
      <div className="mb-4 flex items-center justify-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-white [text-shadow:0_2px_30px_rgba(129,140,248,0.45)]">
          Dashboard
        </h1>
        <select
          data-testid="dashboard-select"
          aria-label="Dashboards"
          value={name}
          onChange={(e) => {
            const next = e.target.value
            // Leaving a dashboard drops its unsaved state: the store is what
            // a pick opens.
            reopen(null)
            patchView(VIEW, { draft: null })
            if (next) setSearchParams({ name: next })
            else setSearchParams({})
          }}
          className="glass-input min-w-48 px-3 py-2 text-sm"
        >
          <option value="">Select a dashboard…</option>
          {name !== '' && !dashboards.some((d) => d.name === name) && (
            <option value={name}>{name}</option>
          )}
          {dashboards.map((d) => (
            <option key={d.name} value={d.name}>
              {d.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          data-testid="dashboard-new-query"
          onClick={() => newQuery()}
          className="glass-btn px-3 py-2 text-sm font-medium"
        >
          New query
        </button>
        <button
          type="button"
          data-testid="dashboard-save"
          onClick={() => void save()}
          disabled={!active || saving}
          className="glass-btn min-w-[5rem] px-3 py-2 text-center text-sm font-medium"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          data-testid="dashboard-edit-queries"
          onClick={() => setShowSql((v) => !v)}
          disabled={!active}
          className={`px-3 py-2 text-sm font-medium ${showSql ? 'glass-btn-primary' : 'glass-btn'}`}
        >
          Edit queries
        </button>
        <GitSyncControls
          kind="dashboard"
          name={name}
          disabled={!name}
          onRestored={() => {
            reopen(null)
            setReloadNonce((n) => n + 1)
          }}
        />
        <ExportImportControls
          kind="dashboard"
          name={name}
          onImported={() => {
            // The imported file may carry any dashboard name: refresh the
            // dropdown, and re-load the open one in case it was overwritten.
            void loadDashboards()
            reopen(null)
            setReloadNonce((n) => n + 1)
          }}
        />
      </div>

      {showSql && active && (
        <DashboardSqlPanel
          queries={active.queries}
          onChange={editQuery}
          onExecute={() => void execute()}
          remoteId={remoteId}
        />
      )}

      {!name && !active && (
        <p className="text-center text-sm text-slate-400" data-testid="dashboard-empty">
          {dashboards.length
            ? 'Pick a dashboard to view it.'
            : 'No dashboards yet. An agent can create one with the push_dashboard tool.'}
        </p>
      )}

      {error && (
        <p
          className="rounded-xl border border-red-400/40 bg-red-500/10 px-4 py-3 text-center text-sm text-red-200"
          data-testid="dashboard-error"
        >
          {error}
        </p>
      )}

      {!error && loading && !(active && results) && (
        <p className="text-center text-sm text-slate-400" data-testid="dashboard-loading">
          Running queries…
        </p>
      )}

      {active && results && (
        <DashboardFrame
          key={loadSeq}
          ref={frameRef}
          html={active.html}
          results={results}
          params={params}
        />
      )}
    </div>
  )
}

export default DashboardView
