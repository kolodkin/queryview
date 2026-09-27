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

import { SearchPanel, useCopy, useDismiss } from '../core'
import { isReady, type Connection } from './connection'
import QueryView, { type QueryPush } from './QueryView'
import DashboardView, { type DashboardPush } from './DashboardView'
import ExplorerView from './ExplorerView'
import { Toast } from './controls/Toast'
import { Loading } from './controls/Spinner'
import WorkspaceSwitcher from './controls/WorkspaceSwitcher'
import SessionSwitcher from './controls/SessionSwitcher'
import {
  attachSession,
  currentSession,
  patchSession,
  releaseSession,
  selectSession,
  sessionId,
  startHeartbeat,
  type SessionState,
} from './session'
import { apiFetch } from './api'

// The database list behind the connection pill. Long connections list hundreds
// of databases, so it carries the landing picker's filter.
function DatabaseMenu({
  connection,
  onSelect,
}: {
  connection: Connection
  onSelect: (database: string) => void
}) {
  return (
    <SearchPanel
      items={connection.databases}
      nameOf={(db) => db}
      noun="databases"
      testid="db-select"
      isSelected={(db) => db === connection.database}
      onPick={onSelect}
      className="left-0 w-64"
      renderItem={(db, current) => (
        <span className={`truncate ${current ? 'text-indigo-200' : 'text-slate-200'}`}>{db}</span>
      )}
      itemAction={(db) => <CopyName name={db} />}
    />
  )
}

// Copies a database name without picking it; dim until its row is hovered.
function CopyName({ name }: { name: string }) {
  const [copied, copy] = useCopy()
  return (
    <button
      type="button"
      data-testid="db-copy"
      aria-label={`Copy ${name}`}
      title={copied ? 'Copied' : 'Copy name'}
      onClick={() => void copy(name)}
      className="shrink-0 rounded px-2 py-1.5 text-xs text-slate-500 group-hover:text-slate-300 hover:!text-indigo-200"
    >
      {copied ? (
        '✓'
      ) : (
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="9" width="11" height="11" rx="2" />
          <path d="M5 15V5a2 2 0 0 1 2-2h10" />
        </svg>
      )}
    </button>
  )
}

// App shell: routing, shared connection state, the connection pill + agent
// popover, and the armed/SSE remote-control channel. Pages: /queries,
// /explorer, /dashboard.
function Shell() {
  const navigate = useNavigate()
  const location = useLocation()
  const [connection, setConnection] = useState<Connection | null>(null)
  const ready = isReady(connection)
  const [armed, setArmed] = useState(false)
  const [channelOpen, setChannelOpen] = useState(false)
  const [agentOpen, setAgentOpen] = useState(false)
  const [queryPush, setQueryPush] = useState<QueryPush | null>(null)
  const [dashboardPush, setDashboardPush] = useState<DashboardPush | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [dbOpen, setDbOpen] = useState(false)
  // Seeded from the session once it attaches.
  const [workspace, setWorkspace] = useState('')
  const [sessionLabel, setSessionLabel] = useState('Session')
  // Panels hydrate from the session at mount, so they must remount when the
  // session changes — not only when the workspace does. Every adoption bumps
  // it, even of the same id: a take-over brings back state another tab wrote.
  const [sessionKey, setSessionKey] = useState('')
  const adoptions = useRef(0)
  // Whether the initial /api/session probe has answered. The `/` route waits on
  // it: until the session is known it can't tell a connected visitor (who wants
  // the explorer) from a disconnected one (who wants the prompt).
  const [sessionChecked, setSessionChecked] = useState(false)
  // Another tab took this tab's session; the page greys out until one is picked.
  const [taken, setTaken] = useState(false)

  const dbRef = useDismiss<HTMLDivElement>(dbOpen, () => setDbOpen(false))
  const agentRef = useDismiss<HTMLDivElement>(agentOpen, () => setAgentOpen(false))
  const [navOpen, setNavOpen] = useState(false)
  const navRef = useDismiss<HTMLDivElement>(navOpen, () => setNavOpen(false))

  function switchWorkspace(name: string) {
    void patchSession({ workspace: name })
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
      const res = await apiFetch('/api/db/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const data = await res.json()
      if (data.ok) {
        const opened = {
          name: data.name as string,
          type: (data.type ?? 'clickhouse') as string,
          databases: (data.databases ?? []) as string[],
          database: null,
        }
        setConnection(opened)
        // Ready already (a picker-less driver) means tables to browse;
        // otherwise the prompt is where the database gets picked.
        navigate(isReady(opened) ? '/explorer' : '/queries')
        return
      }
    } catch {
      /* a failed deep-link open just leaves us disconnected */
    }
    navigate('/queries')
  }

  // The live connection for the attached session. `/api/session` reads that
  // session's own row now, so this is a per-session question.
  async function refreshConnection() {
    try {
      const probe = await (await apiFetch('/api/session')).json()
      if (!probe.connected) {
        setConnection(null)
        return
      }
      setConnection({
        name: probe.name as string,
        type: (probe.type ?? 'clickhouse') as string,
        databases: (probe.databases ?? []) as string[],
        database: (probe.database ?? null) as string | null,
      })
    } catch {
      /* leave the connection as-is */
    }
  }

  // Make the whole shell match a session the tab just moved to: a switch, a
  // take-over, or one the server handed over because the old one is gone.
  function applySession(next: SessionState) {
    setTaken(false)
    setWorkspace(next.workspace)
    setSessionLabel(next.label)
    setSessionKey(`${next.id}:${++adoptions.current}`)
    navigate(next.url || '/queries')
    void refreshConnection()
  }

  // The session decides the landing page, the live connection and what the
  // query panel holds, so nothing renders until this resolves. Which session a
  // tab gets is the server's call — see attach() in backend/queryview/sessions.py.
  useEffect(() => {
    let stopHeartbeat = () => {}
    void (async () => {
      try {
        const restored = await attachSession()
        setWorkspace(restored.workspace)
        setSessionLabel(restored.label)
        setSessionKey(restored.id)
        // Only `/` restores the remembered URL. A deep link is what the user
        // asked for, so it wins and is written into the session instead.
        if (window.location.pathname === '/' && restored.url) {
          navigate(restored.url, { replace: true })
        }
        if (initialConnection) {
          await openConnection(initialConnection)
        } else if (restored.connection) {
          await refreshConnection()
        }
        stopHeartbeat = startHeartbeat({
          onChanged: applySession,
          onTaken: () => setTaken(true),
        })
      } catch {
        /* no session: the app still runs, it just remembers nothing */
      }
      setSessionChecked(true)
    })()
    window.addEventListener('pagehide', releaseSession)
    return () => {
      stopHeartbeat()
      window.removeEventListener('pagehide', releaseSession)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The URL is session state: it is what a refresh and a session switch
  // restore. Immediate rather than queued — navigation is a discrete act,
  // and a refresh right after it must land on the new page.
  useEffect(() => {
    if (!sessionChecked) return
    const url = `${location.pathname}${location.search}`
    // Skip the no-op write on load, where this fires with the URL attach just
    // restored.
    if (url === currentSession()?.url) return
    void patchSession({ url })
  }, [sessionChecked, location.pathname, location.search])


  // When armed, open an SSE channel: `ready` gives the session id; `query` and
  // `dashboard` events carry payloads that navigate to the matching page.
  useEffect(() => {
    if (!armed) return
    // EventSource cannot send headers, so the session id travels in the query
    // string; the backend falls back to X-QV-Session for other callers.
    const es = new EventSource(
      `/api/remote/events?session=${encodeURIComponent(sessionId() ?? '')}`,
    )
    es.addEventListener('ready', () => setChannelOpen(true))
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
      setChannelOpen(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [armed])

  function toggleArm(e: React.ChangeEvent<HTMLInputElement>) {
    setArmed(e.target.checked)
  }

  // Switch the active database for the current connection (via the pill dropdown).
  async function switchDatabase(database: string) {
    setDbOpen(false)
    if (!connection || database === connection.database) return
    try {
      const res = await apiFetch('/api/db/database', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ database }),
      })
      if (res.ok) setConnection({ ...connection, database })
    } catch {
      /* leave the connection as-is on a failed switch */
    }
  }

  // The channel is keyed by this session, so the agent's id is the session's own.
  const remoteId = channelOpen ? sessionId() : null
  const agentCommand = `Use the queryview mcp to connect to session "${remoteId ?? ''}"`

  const navLinkClass = (path: string) =>
    `glass-toggle shrink-0 px-2 py-1.5 text-sm sm:px-3 ${
      location.pathname.startsWith(path) ? 'is-active' : ''
    }`

  return (
    <main className="relative flex min-h-screen items-center-safe justify-center-safe px-6 py-10 text-slate-100">
      {/* One row: labels truncate as the window narrows instead of the two
          groups overlapping. */}
      <header className="absolute inset-x-4 top-4 z-10 flex items-center gap-2">
        {ready && connection && (
          <div className="flex min-w-0 items-center gap-2">
            <div ref={dbRef} className="relative min-w-0">
              <button
                type="button"
                data-testid="connection-status"
                onClick={() => connection.databases.length > 0 && setDbOpen((o) => !o)}
                aria-haspopup="listbox"
                aria-expanded={dbOpen}
                className="glass-chip flex max-w-full items-center gap-2 px-3 py-1.5 text-sm font-medium"
              >
                <span
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-500"
                  data-testid="connection-indicator"
                  aria-label="connected"
                />
                <span className="truncate">
                  <span className="hidden md:inline">connected - </span>
                  {connection.database ?? connection.name}
                </span>
                {connection.databases.length > 0 && (
                  <span className="text-xs text-slate-400">▾</span>
                )}
              </button>
              {dbOpen && connection.databases.length > 0 && (
                <DatabaseMenu
                  connection={connection}
                  onSelect={(db) => void switchDatabase(db)}
                />
              )}
            </div>
            <div ref={agentRef} className="relative shrink-0">
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

        <nav ref={navRef} className="relative ml-auto min-w-0" data-testid="nav">
          <button
            type="button"
            data-testid="nav-menu"
            onClick={() => setNavOpen((o) => !o)}
            aria-expanded={navOpen}
            className="glass-toggle px-3 py-1.5 text-sm md:hidden"
          >
            ☰ {pageTitle(location.pathname)}
          </button>
          {/* One set of controls: an inline row from `md` up, a dropdown panel
              below it, so nothing renders twice. */}
          <div className={`${navOpen ? 'flex' : 'hidden'} ${NAV_PANEL} ${NAV_ROW}`}>
            <SessionSwitcher
              label={sessionLabel}
              onRenamed={setSessionLabel}
              onSwitch={applySession}
            />
            <WorkspaceSwitcher workspace={workspace} onSwitch={switchWorkspace} />
            <Link
              to="/queries"
              data-testid="nav-queries"
              onClick={() => setNavOpen(false)}
              className={navLinkClass('/queries')}
            >
              Queries
            </Link>
            <Link
              to="/explorer"
              data-testid="nav-explorer"
              onClick={() => setNavOpen(false)}
              className={navLinkClass('/explorer')}
            >
              Explorer
            </Link>
            <Link
              to="/dashboard"
              data-testid="nav-dashboard"
              onClick={() => setNavOpen(false)}
              className={navLinkClass('/dashboard')}
            >
              Dashboard
            </Link>
          </div>
        </nav>
      </header>

      {/* Every view hydrates from the session, so none may mount before the
          attach has answered. */}
      {sessionChecked ? (
        <Routes>
          <Route
            path="/queries"
            element={
              <QueryView
                key={`${sessionKey}:${workspace}`}
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
                key={`${sessionKey}:${workspace}`}
                pushed={dashboardPush}
                onPushConsumed={() => setDashboardPush(null)}
                runOn={connection ? `${connection.name}/${connection.database ?? ''}` : null}
              />
            }
          />
          {/* Only `/` picks a landing page. An unknown path is just a bad URL,
              not a landing question. */}
          <Route path="/" element={<Navigate to={ready ? '/explorer' : '/queries'} replace />} />
          <Route path="*" element={<Navigate to="/queries" replace />} />
        </Routes>
      ) : (
        <Loading label="Restoring session…" testid="session-loading" />
      )}
      <Toast message={toast} onDone={() => setToast(null)} />
      {taken && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Session open in another tab"
          data-testid="session-taken"
          className="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-6 backdrop-blur-sm backdrop-grayscale"
        >
          <div className="glass-popover w-80 space-y-3 p-5 text-sm">
            <p className="font-medium text-slate-100">{sessionLabel} is open in another tab.</p>
            <p className="text-slate-400">This tab is paused so the two don't overwrite each other.</p>
            <div className="flex gap-2">
              <button
                type="button"
                data-testid="session-take-over"
                onClick={() => void selectSession(sessionId(), true).then((n) => n && applySession(n))}
                className="glass-btn-primary px-3 py-1.5"
              >
                Use it here
              </button>
              <button
                type="button"
                data-testid="session-taken-new"
                onClick={() => void selectSession(null).then((n) => n && applySession(n))}
                className="glass-btn px-3 py-1.5"
              >
                New session
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}

// The right-hand controls: a popover panel below `md`, stripped back to a plain
// row from `md` up.
const NAV_PANEL = 'glass-popover absolute right-0 top-full mt-2 w-56 flex-col gap-2 p-2'
const NAV_ROW =
  'md:static md:mt-0 md:flex md:w-auto md:min-w-0 md:flex-row md:border-0 md:bg-transparent md:p-0 md:shadow-none md:backdrop-filter-none'

function pageTitle(path: string): string {
  if (path.startsWith('/explorer')) return 'Explorer'
  if (path.startsWith('/dashboard')) return 'Dashboard'
  return 'Queries'
}

function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  )
}

export default App
