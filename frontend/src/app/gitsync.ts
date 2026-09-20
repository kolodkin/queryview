// Client for the /api/git backup/restore endpoints (see docs/gitsync.md).
// Every operation is scoped to a workspace (see docs/workspace.md).

import { apiFetch } from './api'

export type GitKind = 'query' | 'dashboard'

export type GitRevision = { sha: string; date: number; message: string }

export type GitStoreResult = {
  ok: boolean
  committed?: boolean
  sha?: string | null
  message?: string
}

export type GitHistoryResult = {
  ok: boolean
  revisions?: GitRevision[]
  has_more?: boolean
  message?: string
}

// Whether git sync is configured is per-workspace server state — cache one
// probe per workspace, cleared when workspace settings change.
const statusCache = new Map<string, Promise<boolean>>()

export function gitStatus(workspace: string): Promise<boolean> {
  let cached = statusCache.get(workspace)
  if (!cached) {
    cached = (async () => {
      try {
        const r = await (
          await apiFetch(`/api/git/status?workspace=${encodeURIComponent(workspace)}`)
        ).json()
        return Boolean(r.configured)
      } catch {
        return false
      }
    })()
    statusCache.set(workspace, cached)
  }
  return cached
}

export function invalidateGitStatus(): void {
  statusCache.clear()
}

export async function gitStore(
  kind: GitKind,
  name: string,
  connType?: string,
  workspace?: string,
): Promise<GitStoreResult> {
  const res = await apiFetch('/api/git/store', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, name, conn_type: connType, workspace }),
  })
  return res.json()
}

export async function gitHistory(
  kind: GitKind,
  name: string,
  opts: { connType?: string; before?: string; limit?: number; workspace?: string } = {},
): Promise<GitHistoryResult> {
  const params = new URLSearchParams({ kind, name })
  if (opts.connType) params.set('conn_type', opts.connType)
  if (opts.before) params.set('before', opts.before)
  if (opts.limit) params.set('limit', String(opts.limit))
  if (opts.workspace) params.set('workspace', opts.workspace)
  const res = await apiFetch(`/api/git/history?${params.toString()}`)
  return res.json()
}

export async function gitRestore(
  kind: GitKind,
  name: string,
  ref: string,
  connType?: string,
  workspace?: string,
): Promise<{ ok: boolean; message?: string }> {
  const res = await apiFetch('/api/git/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, name, conn_type: connType, ref, workspace }),
  })
  return res.json()
}

// Merge a fetched page into the already-loaded revisions, dropping any shas
// we already have (pages can overlap if a commit lands mid-scroll).
export function appendRevisions(
  existing: GitRevision[],
  page: GitRevision[],
): GitRevision[] {
  const seen = new Set(existing.map((r) => r.sha))
  return [...existing, ...page.filter((r) => !seen.has(r.sha))]
}
