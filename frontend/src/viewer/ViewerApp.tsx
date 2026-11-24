// The viewer server's page (docs/viewer_server): pick a connection and a
// dashboard, and see it as the app's dashboard page shows it. Display only:
// it sends names and parameter values, never SQL.

import { useEffect, useRef, useState } from 'react'

import {
  DashboardFrame,
  answerSnapshot,
  answerWidget,
  listenToFrame,
  requestSnapshot,
  valuesOf,
  widgetPage,
  widgetQueryNames,
  withKeptText,
  type DashboardResults,
  type PendingSnapshot,
  type ResolvedParam,
} from '../core'
import { getJson, postJson } from './api'
import {
  pickSelection,
  readStored,
  selectionSearch,
  writeStored,
  type Selection,
} from './selection'

type Dashboard = { name: string; html: string; queries: string[] }
// What the frame is built from: one load of one dashboard on one connection.
type Shown = { dashboard: Dashboard; results: DashboardResults; params: ResolvedParam[] }

const names = (body: unknown): string[] =>
  Array.isArray(body) ? body.map((item) => String((item as { name?: unknown }).name ?? '')) : []

function ViewerApp() {
  const [connections, setConnections] = useState<string[]>([])
  const [dashboards, setDashboards] = useState<string[]>([])
  // Null until the lists have loaded and a pick could be made.
  const [selection, setSelection] = useState<Selection | null>(null)
  const [shown, setShown] = useState<Shown | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  // Bumped per load, keying the frame so a re-pick never reuses a stale one.
  const [loadSeq, setLoadSeq] = useState(0)
  const frameRef = useRef<HTMLIFrameElement>(null)
  // The selectors as last resolved: what a widget's query runs with.
  const resolvedRef = useRef<ResolvedParam[]>([])
  // The page-query results the frame holds as `window.queries`.
  const shownResultsRef = useRef<DashboardResults>({})
  // A Snapshot waiting for the frame's serialized document.
  const snapshotRef = useRef<PendingSnapshot | null>(null)

  // The lists, then the opening pick: the URL, else the last pick, else the
  // first connection. Back/forward re-reads the URL.
  useEffect(() => {
    let cancelled = false
    let loaded: { connections: string[]; dashboards: string[] } | null = null
    const pick = () => {
      if (!loaded) return
      setSelection(
        pickSelection(window.location.search, readStored(), loaded.connections, loaded.dashboards),
      )
    }
    void (async () => {
      const [conns, dashes] = await Promise.all([
        getJson('/api/connections'),
        getJson('/api/dashboards'),
      ])
      if (cancelled) return
      if (conns.status !== 200 || dashes.status !== 200) {
        setError('Failed to load the dashboards.')
        return
      }
      loaded = { connections: names(conns.body), dashboards: names(dashes.body) }
      setConnections(loaded.connections)
      setDashboards(loaded.dashboards)
      pick()
    })()
    window.addEventListener('popstate', pick)
    return () => {
      cancelled = true
      window.removeEventListener('popstate', pick)
    }
  }, [])

  // A pick the user made: remembered, and in the URL so it can be shared.
  function choose(next: Selection) {
    writeStored(next)
    window.history.pushState(null, '', `${window.location.pathname}${selectionSearch(next)}`)
    setSelection(next)
  }

  const connection = selection?.connection ?? ''
  const dashboard = selection?.dashboard ?? ''

  // Load the picked dashboard and run its own queries on the picked
  // connection; the queries its widgets name run per widget instead.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      setShown(null)
      setError(null)
      // Also ends a load this pick cancelled.
      setLoading(Boolean(connection && dashboard))
      if (!connection || !dashboard) return
      const got = await getJson(`/api/dashboards/${encodeURIComponent(dashboard)}`)
      if (cancelled) return
      if (got.status !== 200) {
        setLoading(false)
        setError(
          got.status === 404 ? `Dashboard “${dashboard}” not found.` : 'Failed to load dashboard.',
        )
        return
      }
      const dash = got.body as Dashboard
      const widgets = new Set(widgetQueryNames(dash.html))
      const run = await postJson('/api/run', {
        connection,
        dashboard,
        queries: dash.queries.filter((q) => !widgets.has(q)),
        values: {},
      })
      if (cancelled) return
      setLoading(false)
      if (!run.ok) {
        setError(String(run.message ?? 'Failed to run queries.'))
        return
      }
      const results = (run.results ?? {}) as DashboardResults
      const params = (run.params ?? []) as ResolvedParam[]
      resolvedRef.current = params
      shownResultsRef.current = results
      setShown({ dashboard: dash, results, params })
      setLoadSeq((n) => n + 1)
    })()
    return () => {
      cancelled = true
    }
  }, [connection, dashboard])

  // Answer the open dashboard's frame: its setParams (values only), its
  // widgets and its snapshot. Every request names the dashboard's own queries.
  useEffect(() => {
    if (!shown) return
    const on = { connection, dashboard: shown.dashboard.name }
    const widgets = new Set(widgetQueryNames(shown.dashboard.html))
    const own = shown.dashboard.queries.filter((q) => !widgets.has(q))
    return listenToFrame(() => [frameRef.current], {
      onSnapshot: (snap, frame) => answerSnapshot(snapshotRef, snap, frame),
      onWidget: (req) =>
        answerWidget(
          req,
          (kind, r) =>
            postJson(`/api/${kind}`, {
              ...on,
              query: r.query,
              values: valuesOf(resolvedRef.current),
              ...widgetPage(r),
            }),
          setError,
        ),
      onSetParams: async (values) => {
        const run = await postJson('/api/run', {
          ...on,
          queries: own,
          values: withKeptText(values, resolvedRef.current),
        })
        const params = run.params as ResolvedParam[] | undefined
        if (params) resolvedRef.current = params
        // Gone from the repo since it was opened: the page says so. A failing
        // query stays the frame's to show, as in the app.
        setError(run.status === 404 ? String(run.message ?? 'Dashboard not found.') : null)
        if (!run.ok)
          return {
            type: 'params-results',
            ok: false,
            message: String(run.message ?? 'Failed to run queries.'),
            params: params ?? [],
          }
        shownResultsRef.current = (run.results ?? {}) as DashboardResults
        return { type: 'params-results', ok: true, results: shownResultsRef.current, params }
      },
    })
  }, [shown, connection])

  // Download the dashboard as one static HTML file (docs/dashboard.md).
  function snapshot() {
    if (shown) requestSnapshot(frameRef, shown.dashboard.name, snapshotRef, setError)
  }

  return (
    <main className="min-h-screen px-3 py-6 text-slate-100" data-testid="viewer">
      <div className="mb-4 flex flex-wrap items-center justify-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-white">QueryView</h1>
        <select
          data-testid="viewer-connection"
          aria-label="Connection"
          value={connection}
          onChange={(e) => choose({ connection: e.target.value, dashboard })}
          className="glass-input min-w-40 px-3 py-2 text-sm"
        >
          {connections.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          data-testid="viewer-dashboard"
          aria-label="Dashboards"
          value={dashboard}
          onChange={(e) => choose({ connection, dashboard: e.target.value })}
          className="glass-input min-w-48 px-3 py-2 text-sm"
        >
          <option value="">Select a dashboard…</option>
          {dashboard !== '' && !dashboards.includes(dashboard) && (
            <option value={dashboard}>{dashboard}</option>
          )}
          {dashboards.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <button
          type="button"
          data-testid="viewer-snapshot"
          onClick={snapshot}
          disabled={!shown}
          title="Download this dashboard as a static HTML file"
          className="glass-btn px-3 py-2 text-sm font-medium"
        >
          Snapshot
        </button>
      </div>

      {error && (
        <p
          className="mb-4 rounded-xl border border-red-400/40 bg-red-500/10 px-4 py-3 text-center text-sm text-red-200"
          data-testid="viewer-error"
        >
          {error}
        </p>
      )}

      {!error && loading && (
        <p className="text-center text-sm text-slate-400" data-testid="viewer-loading">
          Running queries…
        </p>
      )}

      {shown && (
        <DashboardFrame
          key={loadSeq}
          ref={frameRef}
          html={shown.dashboard.html}
          results={shown.results}
          params={shown.params}
        />
      )}
    </main>
  )
}

export default ViewerApp
