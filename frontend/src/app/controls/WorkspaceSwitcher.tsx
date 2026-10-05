import { useEffect, useState } from 'react'
import ExportImportControls from './ExportImportControls'
import { useDismiss } from '../../core'
import {
  announceGitSync,
  gitConflicts,
  invalidateGitStatus,
  gitSync,
  onGitSync,
  type GitConflict,
} from '../gitsync'
import {
  createWorkspace,
  deleteWorkspace,
  listWorkspaces,
  updateWorkspace,
  type Workspace,
  type WorkspaceChanges,
} from '../workspace'
import { announceAutosaveEnabled } from '../autosave'

type Props = {
  workspace: string
  onSwitch: (name: string) => void
  // Settings saved (e.g. autosave toggled), so the shell re-reads them.
  onSaved?: () => void
}

// Header dropdown for the active workspace plus a small manage panel
// (create / rename / set-clear remote / delete), and a warning when the last
// git sync kept local copies the repo disagrees with. Workspace settings are
// admin config; a remote's token is write-only — the server never returns it.
export default function WorkspaceSwitcher({ workspace, onSwitch, onSaved }: Props) {
  const [open, setOpen] = useState(false)
  const [manage, setManage] = useState(false)
  const [list, setList] = useState<Workspace[]>([])
  const [error, setError] = useState('')
  const [conflicts, setConflicts] = useState<GitConflict[]>([])
  const [warnOpen, setWarnOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncNote, setSyncNote] = useState('')
  // Manage-panel form state; empty remote means "leave as-is" on save.
  const [name, setName] = useState('')
  const [remote, setRemote] = useState('')
  const [branch, setBranch] = useState('')
  const [autosave, setAutosave] = useState(false)
  const current = list.find((w) => w.name === workspace)
  const savedAutosave = current?.autosave ?? false
  // The manage panel light-dismisses only while untouched: once it holds
  // unsaved input (a new remote URL above all), it closes through its buttons.
  const dirty =
    manage &&
    (name.trim() !== workspace ||
      remote.trim() !== '' ||
      branch.trim() !== (current?.branch ?? '') ||
      autosave !== savedAutosave)
  const rootRef = useDismiss<HTMLDivElement>(open || warnOpen || (manage && !dirty), () => {
    setOpen(false)
    setWarnOpen(false)
    setManage(false)
  })

  // Conflicts are recorded server-side by each sync, so re-read them after any.
  useEffect(() => {
    let live = true
    const load = () => void gitConflicts(workspace).then((c) => live && setConflicts(c))
    load()
    const off = onGitSync(load)
    return () => {
      live = false
      off()
    }
  }, [workspace])

  async function reload() {
    try {
      setList(await listWorkspaces())
    } catch {
      /* keep the last list */
    }
  }

  useEffect(() => {
    // setList runs after the fetch await, so it doesn't cascade renders.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload()
  }, [])

  function openManage() {
    setManage(true)
    setName(workspace)
    setRemote('')
    setBranch(current?.branch ?? '')
    setAutosave(savedAutosave)
    setError('')
    setSyncNote('')
  }

  async function syncNow() {
    setSyncing(true)
    setSyncNote('')
    const r = await gitSync(workspace).catch(() => ({ ok: false, message: 'sync failed' }) as const)
    setSyncing(false)
    if (!r.ok) {
      setSyncNote(`Sync failed: ${r.message ?? 'unknown error'}`)
      return
    }
    const n = r.imported?.length ?? 0
    const c = r.conflicts?.length ?? 0
    setSyncNote(
      `Synced: ${n ? `imported ${n}` : 'nothing new'}${c ? ` · ${c} differ (see ⚠)` : ''}.`,
    )
  }

  async function saveSettings() {
    const changes: WorkspaceChanges = {}
    if (name.trim() && name.trim() !== workspace) changes.name = name.trim()
    if (remote.trim()) changes.remote = remote.trim()
    if (branch.trim()) changes.branch = branch.trim()
    if (autosave !== savedAutosave) changes.autosave = autosave
    const r = await updateWorkspace(workspace, changes)
    if (!r.ok) {
      setError(r.message ?? 'update failed')
      return
    }
    invalidateGitStatus()
    announceGitSync()
    onSaved?.()
    if (changes.autosave) announceAutosaveEnabled()
    if (r.sync_error) {
      setError(`Saved, but syncing with the repo failed: ${r.sync_error}`)
      return
    }
    setManage(false)
    await reload()
    if (changes.name) onSwitch(changes.name)
  }

  async function create() {
    if (!name.trim()) return
    const r = await createWorkspace(
      name.trim(),
      remote.trim() || undefined,
      branch.trim() || undefined,
      autosave,
    )
    if (!r.ok) {
      setError(r.message ?? 'create failed')
      return
    }
    invalidateGitStatus()
    announceGitSync()
    setManage(false)
    await reload()
    onSwitch(name.trim())
  }

  async function remove() {
    if (!window.confirm(`Delete workspace '${workspace}'? It must be empty.`)) return
    const r = await deleteWorkspace(workspace)
    if (!r.ok) {
      setError(r.message ?? 'delete failed')
      return
    }
    setManage(false)
    await reload()
    if (r.workspace) onSwitch(r.workspace)
  }

  return (
    <div ref={rootRef} className="relative flex min-w-0 items-center gap-1">
      {conflicts.length > 0 && (
        <button
          type="button"
          data-testid="workspace-conflicts"
          aria-label={`${conflicts.length} differ from the git repo`}
          title="Differs from the git repo"
          onClick={() => setWarnOpen((o) => !o)}
          className="shrink-0 rounded-full px-1.5 py-1 text-sm text-amber-300 hover:bg-white/10"
        >
          ⚠
        </button>
      )}
      {warnOpen && conflicts.length > 0 && (
        <div
          data-testid="workspace-conflicts-panel"
          className="glass-popover absolute right-0 top-full z-10 mt-2 w-80 space-y-2 p-3 text-sm"
        >
          <p className="font-medium text-amber-200">
            {conflicts.length === 1 ? '1 item differs' : `${conflicts.length} items differ`} from the git
            repo
          </p>
          <p className="text-xs text-slate-400">
            Both here and in the repo, with different content. Sync never overwrites local work, so
            your version was kept.
          </p>
          <ul className="space-y-1 text-slate-200">
            {conflicts.map((c) => (
              <li key={`${c.kind}/${c.conn_type}/${c.name}`} className="truncate">
                <span className="text-xs text-slate-400">{c.kind}</span> {c.name}
                {c.conn_type && <span className="text-xs text-slate-500"> · {c.conn_type}</span>}
              </li>
            ))}
          </ul>
          <p className="text-xs text-slate-400">
            To settle one, open it and <b className="text-slate-200">Commit</b> to push your version,
            or <b className="text-slate-200">Restore</b> to take the repo&apos;s.
          </p>
        </div>
      )}
      <button
        type="button"
        data-testid="workspace-switcher"
        onClick={() => {
          setOpen((o) => !o)
          if (!open) void reload()
        }}
        className="glass-chip flex max-w-full items-center gap-2 px-3 py-1.5 text-sm font-medium"
      >
        <span className="truncate">{workspace}</span>
        <span className="text-xs text-slate-400">▾</span>
      </button>
      {open && (
        <div className="glass-popover absolute right-0 top-full z-10 mt-2 w-64 p-1 text-sm">
          {list.map((w) => (
            <button
              key={w.name}
              type="button"
              data-testid="workspace-option"
              onClick={() => {
                setOpen(false)
                onSwitch(w.name)
              }}
              className={`block w-full truncate rounded px-2 py-1.5 text-left hover:bg-white/10 ${
                w.name === workspace ? 'text-indigo-200' : 'text-slate-200'
              }`}
            >
              {w.name}
            </button>
          ))}
          <button
            type="button"
            data-testid="workspace-manage"
            onClick={() => {
              setOpen(false)
              openManage()
            }}
            className="mt-1 block w-full rounded border-t border-white/10 px-2 py-1.5 text-left text-xs text-slate-400 hover:bg-white/10"
          >
            Manage workspaces…
          </button>
        </div>
      )}
      {manage && (
        <div className="glass-popover absolute right-0 top-full z-10 mt-2 w-80 space-y-2 p-3 text-sm">
          <div className="text-xs text-slate-400">Workspace name</div>
          <input
            data-testid="workspace-name-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="glass-input w-full px-2 py-1 text-slate-100"
          />
          <div className="text-xs text-slate-400">
            Git remote URL ({current?.remote ? 'leave blank to keep' : 'not set'}; a token is never
            shown back)
          </div>
          <input
            data-testid="workspace-remote-input"
            value={remote}
            onChange={(e) => setRemote(e.target.value)}
            placeholder={current?.remote ?? 'https://user:token@github.com/org/repo.git'}
            className="glass-input w-full px-2 py-1 font-mono text-xs text-slate-100"
          />
          <div className="text-xs text-slate-400">Branch</div>
          <input
            data-testid="workspace-branch-input"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            placeholder="main"
            className="glass-input w-full px-2 py-1 text-slate-100"
          />
          <label className="flex items-start gap-2 text-xs text-slate-300">
            <input
              type="checkbox"
              data-testid="workspace-autosave-input"
              checked={autosave}
              onChange={(e) => setAutosave(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              Autosave — save queries after each successful run and agent pushes as they arrive;
              no Save button. Commit / Restore keep the history.
            </span>
          </label>
          {current?.configured && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="workspace-sync"
                disabled={syncing}
                onClick={() => void syncNow()}
                title="Import what the repo has that this workspace doesn't; never overwrites"
                className="glass-btn px-2 py-1 text-xs"
              >
                {syncing ? 'Syncing…' : 'Sync from repo'}
              </button>
              {syncNote && (
                <span data-testid="workspace-sync-note" className="text-xs text-slate-400">
                  {syncNote}
                </span>
              )}
            </div>
          )}
          <div className="text-xs text-slate-400">
            Export / import the whole workspace (queries + dashboards) as YAML
          </div>
          <ExportImportControls kind="workspace" compact onImported={() => void reload()} />
          <div className="flex gap-2 pt-1">
            <button
              type="button"
              data-testid="workspace-save"
              onClick={() => void saveSettings()}
              className="glass-btn px-2 py-1 text-xs font-medium"
            >
              Save
            </button>
            <button
              type="button"
              data-testid="workspace-create"
              onClick={() => void create()}
              className="glass-btn px-2 py-1 text-xs font-medium"
            >
              Create as new
            </button>
            <button
              type="button"
              data-testid="workspace-delete"
              onClick={() => void remove()}
              className="glass-btn px-2 py-1 text-xs font-medium text-red-300"
            >
              Delete
            </button>
            <button type="button" onClick={() => setManage(false)} className="glass-btn px-2 py-1 text-xs">
              Close
            </button>
          </div>
          {error && (
            <p data-testid="workspace-error" className="text-xs text-red-300">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
