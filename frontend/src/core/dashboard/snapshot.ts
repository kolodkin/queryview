// The dashboard snapshot: the frame serializes its own document on request
// (the prologue in ./srcDoc.ts) and the host wraps that text for download.
// See docs/dashboard.md.

import { escapeHtml } from '../cells/cellView'

// The largest document the host accepts from a frame, in characters.
export const MAX_SNAPSHOT_CHARS = 50_000_000

export type SnapshotResult = { html: string } | { message: string }

export function parseSnapshotResult(data: unknown): SnapshotResult | null {
  if (!data || typeof data !== 'object') return null
  const { type, html, message } = data as { type?: unknown; html?: unknown; message?: unknown }
  if (type !== 'qv-snapshot-result') return null
  if (typeof html === 'string') {
    return html.length <= MAX_SNAPSHOT_CHARS
      ? { html }
      : { message: 'The dashboard is too large to snapshot.' }
  }
  return typeof message === 'string' ? { message } : null
}

// The file to download. The frame's HTML is untrusted, so the policy comes
// first: whatever follows, the file runs no script.
export function snapshotDocument(html: string, title: string): string {
  return (
    '<!doctype html><meta charset="utf-8">' +
    '<meta http-equiv="Content-Security-Policy" content="' +
    "script-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'" +
    '">' +
    `<title>${escapeHtml(title)}</title>\n` +
    // No http-equiv attribute of the frame's survives: a refresh would
    // navigate the opened file away. An attribute name can't be
    // entity-encoded, and only one followed by `=` has a value to act on, so
    // this catches every live one and leaves the words alone in text.
    html.replace(/http-equiv(?=\s*=)/gi, 'data-http-equiv')
  )
}
