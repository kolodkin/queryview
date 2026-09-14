import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom'

import { isReady, type Connection } from './connection'
import QueryView, { type QueryPush } from './QueryView'
import DashboardView, { type DashboardPush } from './DashboardView'
import ExplorerView from './ExplorerView'
import { Toast } from './controls/Toast'
import WorkspaceSwitcher from './controls/WorkspaceSwitcher'
import { useDismiss } from './controls/useDismiss'
import { activeWorkspace, setActiveWorkspace } from './workspace'

// App shell: routing, shared connection state, the connection pill + agent
// popover, and the armed/SSE remote-control channel. Pages: /queries, /dashboard.
function Shell() {
  const navigate = useNavigate()
  const location = useLocation()
  const [connection, setConnection] = useState<Connection | null>(null)
  const ready = isReady(connection)
  const [armed, setArmed] = useState(false)
  const [remoteId, setRemoteId] = useState<string | null>(null)
  const [agentOpen, setAgentOpen] = useState(false)
  const [queryPush, setQueryPush] = useState<QueryPush | null>(null)
  const [dashboardPush, setDashboardPush] = useState<DashboardPush | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [dbOpen, setDbOpen] = useState(false)
  const [workspace, setWorkspace] = useState(activeWorkspace())
  const dbRef = useRef<HTMLDivElement>(null)
  const agentRef = useRef<HTMLDivElement>(null)
  useDismiss(dbRef, dbOpen, () => setDbOpen(false))
  useDismiss(agentRef, agentOpen, () => setAgentOpen(false))

  function switchWorkspace(name: string) {
    setActiveWorkspace(name)
    setWorkspace(name)
  }

  // The ?connection= deep-link, captured before the `/`→`/queries` redirect
  // rewrites the URL.
  const initialConnection = useMemo(
    () => new URLSearchParams(window.location.search).get('connection'),
    [],
  )

  async function openConnection(name: string) {
    try {
      const res = await fetch('/api/db/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const data = await res.json()
      if (data.ok) {
        setConnection({
          name: data.name,
          type: (data.type ?? 'clickhouse') as string,
          databases: (data.databases ?? []) as string[],
          database: null,
        })
      }
    } catch {
      /* a failed deep-link open just leaves us disconnected */
    }
    navigate('/queries')
  }

  // On load: open ?connection=<name> if given, else resume the session's last connection.
  useEffect(() => {
    if (initialConnection) {
      // Async: state is set after the open round-trips.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void openConnection(initialConnection)
      return
    }
    fetch('/api/session')
      .then((r) => r.json())
      .then((s) => {
        if (s.connected) {
          setConnection({
            name: s.name,
            type: s.type ?? 'clickhouse',
            databases: s.databases ?? [],
            database: s.database ?? null,
          })
        }
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // When armed, open an SSE channel: `ready` gives the session id; `query` and
  // `dashboard` events carry payloads that navigate to the matching page.
  useEffect(() => {
    if (!armed) return
    const es = new EventSource('/api/remote/events')
    es.addEventListener('ready', (e) => {
      try {
        setRemoteId(JSON.parse((e as MessageEvent).data).id as string)
      } catch {
        /* ignore malformed event */
      }
    })
    es.addEventListener('query', (e) => {
      try {
        setQueryPush(JSON.parse((e as MessageEvent).data) as QueryPush)
        setToast('Agent updated the query')
        navigate('/queries')
      } catch {
        /* ignore malformed event */
      }
    })
    es.addEventListener('dashboard', (e) => {
      try {
        const payload = JSON.parse((e as MessageEvent).data) as DashboardPush
        setDashboardPush(payload)
        setToast('Agent updated the dashboard')
        navigate(`/dashboard?name=${encodeURIComponent(payload.name)}`)
      } catch {
        /* ignore malformed event */
      }
    })
    return () => {
      es.close()
      setRemoteId(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [armed])

  function toggleArm(e: React.ChangeEvent<HTMLInputElement>) {
    setArmed(e.target.checked)
  }

  // Report the active database and workspace to the live session so the
  // agent's session-scoped tools resolve against them. Fires on arm and on
  // each change.
  useEffect(() => {
    if (!armed || !remoteId) return
    void fetch('/api/remote/db', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: remoteId,
        database: connection?.database ?? null,
        workspace,
      }),
    }).catch(() => {})
  }, [armed, remoteId, connection?.database, workspace])

  // Switch the active database for the current connection (via the pill dropdown).
  async function switchDatabase(database: string) {
    setDbOpen(false)
    if (!connection || database === connection.database) return
    try {
      const res = await fetch('/api/db/database', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ database }),
      })
      if (res.ok) setConnection({ ...connection, database })
    } catch {
      /* leave the connection as-is on a failed switch */
    }
  }

  const agentCommand = `Use the queryview mcp to connect to session "${remoteId ?? ''}"`

  const navLinkClass = (path: string) =>
    `glass-toggle px-3 py-1.5 text-sm ${
      location.pathname.startsWith(path) ? 'is-active' : ''
    }`

  return (
    <main className="relative flex min-h-screen items-center justify-center px-6 py-10 text-slate-100">
      {ready && connection && (
        <div className="absolute left-4 top-4 flex items-center gap-2">
          <div ref={dbRef} className="relative">
            <button
              type="button"
              data-testid="connection-status"
              onClick={() => connection.databases.length > 0 && setDbOpen((o) => !o)}
              aria-haspopup="listbox"
              aria-expanded={dbOpen}
              className="glass-chip flex items-center gap-2 px-3 py-1.5 text-sm font-medium"
            >
              <span
                className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-500"
                data-testid="connection-indicator"
                aria-label="connected"
              />
              connected - {connection.database ?? connection.name}
              {connection.databases.length > 0 && (
                <span className="text-xs text-slate-400">▾</span>
              )}
            </button>
            {dbOpen && connection.databases.length > 0 && (
              <div
                data-testid="db-select"
                role="listbox"
                className="glass-popover absolute left-0 top-full z-10 mt-2 max-h-72 w-64 overflow-auto p-1 text-sm"
              >
                {connection.databases.map((db) => (
                  <button
                    key={db}
                    type="button"
                    role="option"
                    aria-selected={db === connection.database}
                    onClick={() => void switchDatabase(db)}
                    className={`block w-full truncate rounded px-2 py-1.5 text-left hover:bg-white/10 ${
                      db === connection.database ? 'text-indigo-200' : 'text-slate-200'
                    }`}
                  >
                    {db}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div ref={agentRef} className="relative">
            <button
              type="button"
              data-testid="agent-toggle"
              onClick={() => setAgentOpen((o) => !o)}
              aria-label="Remote control"
              className={`flex h-8 w-8 items-center justify-center rounded-full transition ${
                armed ? 'glass-btn-primary' : 'glass-btn text-slate-300'
              }`}
            >
              <svg
                viewBox="0 0 24 24"
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <rect x="4" y="8" width="16" height="11" rx="2" />
                <path d="M12 8V4M9 3h6" />
                <circle cx="9" cy="13" r="1" />
                <circle cx="15" cy="13" r="1" />
              </svg>
            </button>
            {agentOpen && (
              <div
                data-testid="agent-panel"
                className="glass-popover absolute left-0 top-full z-10 mt-2 w-72 p-3 text-sm"
              >
                <label className="flex items-center gap-2 font-medium text-slate-200">
                  <input
                    type="checkbox"
                    data-testid="remote-arm"
                    checked={armed}
                    onChange={toggleArm}
                  />
                  Allow remote control
                </label>
                {armed && remoteId && (
                  <div className="mt-3 space-y-2">
                    <div className="text-xs text-slate-400">Session id</div>
                    <code
                      data-testid="remote-session-id"
                      className="block rounded bg-white/10 px-2 py-1 font-mono text-slate-100"
                    >
                      {remoteId}
                    </code>
                    <button
                      type="button"
                      data-testid="remote-copy"
                      onClick={() => {
                        void navigator.clipboard?.writeText(agentCommand)
                        setAgentOpen(false)
                      }}
                      className="glass-btn px-2 py-1 text-xs font-medium text-indigo-200"
                    >
                      Copy agent command
                    </button>
                    <p className="text-xs text-slate-400">{agentCommand}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <nav className="absolute right-4 top-4 flex gap-2" data-testid="nav">
        <WorkspaceSwitcher workspace={workspace} onSwitch={switchWorkspace} />
        <Link to="/queries" data-testid="nav-queries" className={navLinkClass('/queries')}>
          Queries
        </Link>
        <Link
          to="/explorer"
          data-testid="nav-explorer"
          className={navLinkClass('/explorer')}
        >
          Explorer
        </Link>
        <Link
          to="/dashboard"
          data-testid="nav-dashboard"
          className={navLinkClass('/dashboard')}
        >
          Dashboard
        </Link>
      </nav>

      <Routes>
        <Route
          path="/queries"
          element={
            <QueryView
              key={workspace}
              connection={connection}
              setConnection={setConnection}
              pushed={queryPush}
              onPushConsumed={() => setQueryPush(null)}
              remoteId={remoteId}
            />
          }
        />
        <Route path="/explorer" element={<ExplorerView connection={connection} />} />
        <Route
          path="/dashboard"
          element={
            <DashboardView
              key={workspace}
              pushed={dashboardPush}
              onPushConsumed={() => setDashboardPush(null)}
              database={connection?.database ?? null}
            />
          }
        />
        <Route path="*" element={<Navigate to="/queries" replace />} />
      </Routes>
      <Toast message={toast} onDone={() => setToast(null)} />
    </main>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  )
}

export default App
