// Client for /api/workspaces. The active workspace is session state — see
// activeWorkspace() in session.ts; an omitted workspace param means the
// backend's fallback (the oldest workspace). See docs/workspace.md.

import { apiFetch } from './api'

// `remote` is the URL without any embedded credential; the token never comes back.
// `autosave`: persist on update instead of an explicit Save (docs/workspace.md#autosave).
export type Workspace = {
  name: string
  branch: string
  configured: boolean
  remote: string | null
  autosave: boolean
}

// `sync_error`: saved, but merging the newly attached repo in failed.
// `workspace`: after a delete, where the sessions on it moved.
export type WorkspaceResult = { ok: boolean; message?: string; sync_error?: string; workspace?: string }

export async function listWorkspaces(): Promise<Workspace[]> {
  const r = await (await apiFetch('/api/workspaces')).json()
  return (r.workspaces ?? []) as Workspace[]
}

export async function createWorkspace(
  name: string,
  remote?: string,
  branch?: string,
  autosave = false,
): Promise<WorkspaceResult> {
  const res = await apiFetch('/api/workspaces', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, remote: remote || null, branch: branch || null, autosave }),
  })
  return res.json()
}

export type WorkspaceChanges = {
  name?: string
  remote?: string | null
  branch?: string
  autosave?: boolean
}

export async function updateWorkspace(
  name: string,
  changes: WorkspaceChanges,
): Promise<WorkspaceResult> {
  const res = await apiFetch(`/api/workspaces/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  })
  return res.json()
}

export async function deleteWorkspace(name: string): Promise<WorkspaceResult> {
  const res = await apiFetch(`/api/workspaces/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
  return res.json()
}
