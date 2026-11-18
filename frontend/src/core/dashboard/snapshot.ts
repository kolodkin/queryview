// The dashboard snapshot: the frame serializes its own document on request
// (the prologue in ./srcDoc.ts) and the host wraps that text for download.
// See docs/dashboard.md.

// The largest document the host accepts from a frame.
export const MAX_SNAPSHOT_BYTES = 50_000_000

export function parseSnapshotResult(data: unknown): { html: string } | { message: string } | null {
  if (!data || typeof data !== 'object') return null
  const { type, html, message } = data as { type?: unknown; html?: unknown; message?: unknown }
  if (type !== 'qv-snapshot-result') return null
  if (typeof html === 'string') return html.length <= MAX_SNAPSHOT_BYTES ? { html } : null
  return typeof message === 'string' ? { message } : null
}

const escapeText = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

// The file to download. The frame's HTML is untrusted, so the policy comes
// first: whatever follows, the file runs no script.
export function snapshotDocument(html: string, title: string): string {
  return (
    '<!doctype html><meta charset="utf-8">' +
    '<meta http-equiv="Content-Security-Policy" content="' +
    "script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'" +
    '">' +
    `<title>${escapeText(title)}</title>\n` +
    // No http-equiv of the frame's survives: a refresh would navigate the
    // opened file away. Attribute names can't be entity-encoded around this.
    html.replace(/http-equiv/gi, 'data-http-equiv')
  )
}
