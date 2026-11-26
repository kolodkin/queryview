// The dashboard snapshot: the frame serializes its own document on request
// (the prologue in ./srcDoc.ts) and the host wraps that text for download.
// See docs/system/dashboard.md.

import { escapeHtml } from '../cells/cellView'
import { downloadText } from '../download'

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

// A Snapshot waiting for a frame's serialized document.
export type PendingSnapshot = { frame: HTMLIFrameElement; done: (r: SnapshotResult) => void }
type Ref<T> = { current: T }

// Download the dashboard in the frame on screen as one static HTML file,
// `<title>.html`. Only the frame can read its page, so it serializes itself;
// its answer is untrusted text, wrapped by snapshotDocument. `pending` holds
// the request in flight, answered through answerSnapshot; an answer for a
// frame since switched away says nothing.
export function requestSnapshot(
  frameRef: Ref<HTMLIFrameElement | null>,
  title: string,
  pending: Ref<PendingSnapshot | null>,
  setError: (message: string | null) => void,
): void {
  const frame = frameRef.current
  if (!frame || pending.current?.frame === frame) return
  const unanswered = { message: 'The dashboard did not answer the snapshot request.' }
  pending.current?.done(unanswered) // one left by a dashboard since closed: it says nothing
  const done = (r: SnapshotResult) => {
    pending.current = null
    clearTimeout(timer)
    if (frameRef.current !== frame) return
    setError('html' in r ? null : r.message)
    if ('html' in r) downloadText(`${title}.html`, snapshotDocument(r.html, title), 'text/html')
  }
  const timer = setTimeout(() => done(unanswered), 5000)
  pending.current = { frame, done }
  frame.contentWindow?.postMessage({ type: 'qv-snapshot' }, '*')
}

// A frame's answer: it settles the pending request only when that frame was asked.
export function answerSnapshot(
  pending: Ref<PendingSnapshot | null>,
  result: SnapshotResult,
  frame: HTMLIFrameElement,
): void {
  if (pending.current?.frame === frame) pending.current.done(result)
}
