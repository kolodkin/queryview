// Client for the /api/export and /api/import YAML endpoints (see
// docs/export-import.md). Export downloads a self-describing YAML document;
// import posts one back — the document's `kind` decides what gets written.

import { apiFetch } from './api'

export type ExportKind = 'query' | 'dashboard' | 'workspace'

export type ImportResult = {
  ok: boolean
  kind?: ExportKind
  queries?: number
  dashboards?: number
  message?: string
}

export function exportPath(
  kind: ExportKind,
  opts: { name?: string; connType?: string; workspace?: string } = {},
): string {
  const params = new URLSearchParams({ kind })
  if (opts.name) params.set('name', opts.name)
  if (opts.connType) params.set('conn_type', opts.connType)
  if (opts.workspace) params.set('workspace', opts.workspace)
  return `/api/export?${params.toString()}`
}

// The server names the download via Content-Disposition; fall back to a
// generic name if the header is missing or unparsable.
export function filenameFromDisposition(header: string | null, fallback: string): string {
  const m = /filename="([^"]+)"/.exec(header ?? '')
  return m ? m[1] : fallback
}

export async function fetchExport(
  kind: ExportKind,
  opts: { name?: string; connType?: string; workspace?: string } = {},
): Promise<{ ok: boolean; filename?: string; text?: string; message?: string }> {
  const res = await fetch(exportPath(kind, opts))
  if (!res.ok) {
    try {
      const data = await res.json()
      return { ok: false, message: data.message ?? 'export failed' }
    } catch {
      return { ok: false, message: 'export failed' }
    }
  }
  return {
    ok: true,
    filename: filenameFromDisposition(res.headers.get('Content-Disposition'), `${kind}.yaml`),
    text: await res.text(),
  }
}

export async function importYaml(text: string, workspace?: string): Promise<ImportResult> {
  const params = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  const res = await apiFetch(`/api/import${params}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-yaml' },
    body: text,
  })
  try {
    return (await res.json()) as ImportResult
  } catch {
    return { ok: false, message: 'import failed' }
  }
}

// Hand the browser a text file to save. DOM side effect, kept out of components
// so they stay declarative. Also used for CSV downloads (QueryView).
export function downloadText(filename: string, text: string, mime = 'application/x-yaml'): void {
  const url = URL.createObjectURL(new Blob([text], { type: mime }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
