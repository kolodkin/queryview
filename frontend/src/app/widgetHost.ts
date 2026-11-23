// The app's side of the dashboard widget channel: the request a
// <qv-select-view> makes for the query it named, on the session's connection
// (answered through core's answerWidget), and the page that shows one query.

import { escapeHtml } from '../core'
import { postJson } from './api'

// Requests on their way, by connection, path and body: two tables asking for
// the same page at once (a dashboard widget and the query popup's) share one run.
const inFlight = new Map<string, Promise<Record<string, unknown>>>()

// POST `body` to `path`, sharing a run already on its way. `runOn` is the
// session's connection and database: a run is never shared across a switch.
export function sharedPost(
  runOn: string,
  path: string,
  body: unknown,
): Promise<Record<string, unknown>> {
  const key = JSON.stringify([runOn, path, body])
  let pending = inFlight.get(key)
  if (!pending) {
    pending = postJson(path, body)
      .then((res) => res.json() as Promise<Record<string, unknown>>)
      .catch(() => ({ ok: false, message: 'request failed' }))
      .finally(() => inFlight.delete(key))
    inFlight.set(key, pending)
  }
  return pending
}

// A page of one results table over one query. The frame paints its own
// backdrop; match the app's instead of white.
export function queryViewHtml(query: string): string {
  return (
    '<style>body{margin:0;background:#0c1124}</style>' +
    `<qv-select-view query="${escapeHtml(query)}"></qv-select-view>`
  )
}
