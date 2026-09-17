// Client for /api/workspaces. The active workspace is session state — see
// activeWorkspace() in session.ts; 'default' matches the backend's fallback for
// an omitted workspace param. See docs/workspace.md.

import { apiFetch } from './api'

export type Workspace = { name: string; branch: string; configured: boolean }

export type WorkspaceResult = { ok: boolean; message?: string }

export async function listWorkspaces(): Promise<Workspace[]> {
  const r = await (await apiFetch('/api/workspaces')).json()
  return (r.workspaces ?? []) as Workspace[]
}

export async function createWorkspace(
  name: string,
  remote?: string,
  branch?: string,
): Promise<WorkspaceResult> {
  const res = await apiFetch('/api/workspaces', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, remote: remote || null, branch: branch || null }),
  })
  return res.json()
}

export async function updateWorkspace(
  name: string,
  changes: { name?: string; remote?: string | null; branch?: string },
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
