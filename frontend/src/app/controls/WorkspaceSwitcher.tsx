import { useEffect, useState } from 'react'
import ExportImportControls from './ExportImportControls'
import { useDismiss } from '../../core'
import { invalidateGitStatus } from '../gitsync'
import {
  createWorkspace,
  deleteWorkspace,
  listWorkspaces,
  updateWorkspace,
  type Workspace,
} from '../workspace'

type Props = {
  workspace: string
  onSwitch: (name: string) => void
}

// Header dropdown for the active workspace plus a small manage panel
// (create / rename / set-clear remote / delete). Workspace settings are admin
// config; the remote URL is write-only here — the server never returns it.
export default function WorkspaceSwitcher({ workspace, onSwitch }: Props) {
  const [open, setOpen] = useState(false)
  const [manage, setManage] = useState(false)
  const [list, setList] = useState<Workspace[]>([])
  const [error, setError] = useState('')
  // Manage-panel form state; empty remote means "leave as-is" on save.
  const [name, setName] = useState('')
  const [remote, setRemote] = useState('')
  const [branch, setBranch] = useState('')
  // Only the menu light-dismisses: the manage panel holds unsaved form input
  // (including a write-only remote URL), so it closes through its own Close.
  const rootRef = useDismiss<HTMLDivElement>(open, () => setOpen(false))

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
    setBranch(list.find((w) => w.name === workspace)?.branch ?? '')
    setError('')
  }

  async function saveSettings() {
    const changes: { name?: string; remote?: string | null; branch?: string } = {}
    if (name.trim() && name.trim() !== workspace) changes.name = name.trim()
    if (remote.trim()) changes.remote = remote.trim()
    if (branch.trim()) changes.branch = branch.trim()
    const r = await updateWorkspace(workspace, changes)
    if (!r.ok) {
      setError(r.message ?? 'update failed')
      return
    }
    invalidateGitStatus()
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
    )
    if (!r.ok) {
      setError(r.message ?? 'create failed')
      return
    }
    invalidateGitStatus()
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
    onSwitch('default')
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        data-testid="workspace-switcher"
        onClick={() => {
          setOpen((o) => !o)
          if (!open) void reload()
        }}
        className="glass-chip flex items-center gap-2 px-3 py-1.5 text-sm font-medium"
      >
        {workspace}
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
            className="w-full rounded bg-white/10 px-2 py-1 text-slate-100"
          />
          <div className="text-xs text-slate-400">
            Git remote URL (leave blank to keep; settings are write-only)
          </div>
          <input
            data-testid="workspace-remote-input"
            value={remote}
            onChange={(e) => setRemote(e.target.value)}
            placeholder="https://user:token@github.com/org/repo.git"
            className="w-full rounded bg-white/10 px-2 py-1 font-mono text-xs text-slate-100"
          />
          <div className="text-xs text-slate-400">Branch</div>
          <input
            data-testid="workspace-branch-input"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            placeholder="main"
            className="w-full rounded bg-white/10 px-2 py-1 text-slate-100"
          />
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
