import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { DashboardFrame, type DashboardResults } from '../core'
import ExportImportControls from './controls/ExportImportControls'
import GitSyncControls from './controls/GitSyncControls'
import { apiFetch } from './api'
import { activeWorkspace } from './session'

export type DashboardPush = {
  name: string
  connection: string
  html: string
  queries: Record<string, string>
}

type DashboardSummary = { name: string; connection: string; updated_at: number }

// The dashboard page (`/dashboard?name=x`). Picks a saved dashboard (dropdown or
// `?name=`), runs its queries via /api/runqueries, and renders the agent HTML in
// a sandboxed iframe with results injected as `window.queries`. A pushed
// dashboard renders without a refetch.
function DashboardView({
  pushed,
  onPushConsumed,
  database,
}: {
  pushed?: DashboardPush | null
  onPushConsumed?: () => void
  // Active connection database; a change re-runs the dashboard's queries.
  database?: string | null
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const name = searchParams.get('name') ?? ''

  const [dashboards, setDashboards] = useState<DashboardSummary[]>([])
  // Captured locally so consuming the shell push doesn't re-trigger resolve.
  const [localPush, setLocalPush] = useState<DashboardPush | null>(null)
  const [active, setActive] = useState<DashboardPush | null>(null)
  const [results, setResults] = useState<DashboardResults | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  // Bumped after a git restore to re-trigger the load effect below without
  // otherwise changing its dependencies.
  const [reloadNonce, setReloadNonce] = useState(0)

  // Refetch the dropdown list (also used after a Save to surface a new name).
  async function loadDashboards() {
    try {
      const d = await (await apiFetch(`/api/dashboards?workspace=${encodeURIComponent(activeWorkspace())}`)).json()
      setDashboards((d.dashboards ?? []) as DashboardSummary[])
    } catch {
      /* non-fatal; keep the last list */
    }
  }

  // User-only persist: an agent push renders a draft; this Save writes the
  // currently-active dashboard (draft or loaded) to the store.
  async function save() {
    if (!active) return
    setSaving(true)
    setError(null)
    try {
      const res = await apiFetch('/api/dashboards', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: active.name,
          connection: active.connection,
          html: active.html,
          queries: active.queries,
          workspace: activeWorkspace(),
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || !data.ok) {
        setError(data.message ?? 'Failed to save dashboard.')
        return
      }
      await loadDashboards()
    } catch {
      setError('Failed to save dashboard.')
    } finally {
      setSaving(false)
    }
  }

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
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLocalPush(pushed)
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
      if (!name) return

      const dash = await loadDashboard()
      if (cancelled || !dash) return
      setActive(dash)

      setLoading(true)
      try {
        const res = await apiFetch('/api/runqueries', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ connection: dash.connection, queries: dash.queries }),
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok || !data.ok) {
          if (!cancelled) setError(data.message ?? 'Failed to run queries.')
          return
        }
        if (!cancelled) setResults((data.results ?? {}) as DashboardResults)
      } catch {
        if (!cancelled) setError('Failed to run queries.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void resolve()
    return () => {
      cancelled = true
    }
  }, [name, localPush, database, reloadNonce])

  return (
    <div className="w-full max-w-[80vw]" data-testid="dashboard-view">
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
          data-testid="dashboard-save"
          onClick={() => void save()}
          disabled={!active || saving}
          className="glass-btn min-w-[5rem] px-3 py-2 text-center text-sm font-medium"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <GitSyncControls
          kind="dashboard"
          name={name}
          disabled={!name}
          onRestored={() => {
            setLocalPush(null)
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
            setLocalPush(null)
            setReloadNonce((n) => n + 1)
          }}
        />
      </div>

      {!name && (
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

      {name && !error && loading && !(active && results) && (
        <p className="text-center text-sm text-slate-400" data-testid="dashboard-loading">
          Running queries…
        </p>
      )}

      {active && results && <DashboardFrame html={active.html} results={results} />}
    </div>
  )
}

export default DashboardView
