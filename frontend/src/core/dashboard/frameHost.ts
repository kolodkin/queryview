// The host's side of the dashboard frame channel: dispatch the frame's
// messages and answer its widgets. Core never fetches, so the page that hosts
// the frame passes the transport in: the app posts the dashboard's own SQL
// template to its session, the viewer server's page posts names only.

import { downloadText } from '../download'
import { parseParamsRequest } from './params'
import { parseSnapshotResult, type SnapshotResult } from './snapshot'
import {
  failureReply,
  parseWidgetRequest,
  rejectedWidgetReply,
  type WidgetReply,
  type WidgetRequest,
} from './widgetChannel'

// Run (`query`, also a CSV) or describe the query a widget named, returning the
// backend's JSON reply; `{ok: false, message}` says why it can't.
export type WidgetPost = (
  kind: 'query' | 'describe',
  req: WidgetRequest,
) => Promise<Record<string, unknown>>

// The paging a widget request carries, as the query endpoints take it.
export function widgetPage(req: WidgetRequest): Record<string, unknown> {
  if (req.type === 'widget-describe') return {}
  const page = { limit: req.limit, offset: req.offset, order_by: req.orderBy }
  return req.type === 'widget-csv' ? { ...page, format: 'csv' } : page
}

// Answer one widget request; null when there is nothing to post back (CSV).
export async function answerWidget(
  req: WidgetRequest,
  post: WidgetPost,
  // A CSV request has no reply to carry its failure; the host shows it.
  onCsvError: (message: string) => void,
): Promise<WidgetReply | null> {
  const kind = req.type === 'widget-describe' ? 'describe' : 'query'
  let d: Record<string, unknown>
  try {
    d = await post(kind, req)
  } catch {
    d = { ok: false, message: 'request failed' }
  }
  if (req.type === 'widget-csv') {
    if (d.ok) downloadText('query.csv', String(d.output ?? ''), 'text/csv')
    else onCsvError(String(d.message ?? 'download failed'))
    return null
  }
  if (!d.ok) return failureReply(req.type, req.id, String(d.message ?? `${kind} failed`))
  if (req.type === 'widget-describe') {
    return { type: 'widget-fields', id: req.id, ok: true, fields: (d.fields ?? []) as never }
  }
  return {
    type: 'widget-result',
    id: req.id,
    ok: true,
    meta: (d.meta ?? []) as never,
    data: (d.data ?? []) as never,
  }
}

export type FrameHandlers = {
  // A frame's answer to a snapshot request.
  onSnapshot(result: SnapshotResult, frame: HTMLIFrameElement): void
  // A widget's request; the reply is posted back to it (null: nothing to post).
  onWidget(req: WidgetRequest): Promise<WidgetReply | null>
  // The page's setParams, values only; resolves to the params-results message,
  // or null when the run was dropped (its dashboard is gone).
  onSetParams(values: Record<string, string>): Promise<Record<string, unknown> | null>
}

// A re-run's answer, or null when it was dropped.
type Rerun = () => Promise<Record<string, unknown> | null>
export type MarkedRun = (run: Rerun) => Promise<Record<string, unknown> | null>

// Runs a re-run for `frames`: they carry the loading mark from its start until
// the last one still running has answered, and each answer is posted to them all.
export function markedRuns(frames: () => (HTMLIFrameElement | null)[]): MarkedRun {
  const all = (message: unknown) => {
    for (const f of frames()) f?.contentWindow?.postMessage(message, '*')
  }
  let running = 0
  return async (run) => {
    running++
    all({ type: 'qv-loading', on: true })
    try {
      const answer = await run()
      if (answer) all(answer)
      return answer
    } finally {
      if (--running === 0) all({ type: 'qv-loading', on: false })
    }
  }
}

// Dispatch the messages of the frames showing one dashboard (its page, and any
// other view of its queries) to `handlers`, ignoring every other window: a
// frame sends values and names only, never SQL. A widget is answered in the
// frame that asked; a re-run's results, and the loading mark around it, go to
// every frame at once, so their tables re-query together. Returns the unsubscribe.
export function listenToFrame(
  frames: () => (HTMLIFrameElement | null)[],
  handlers: FrameHandlers,
  // The host's own, when it also starts re-runs itself (the app's Execute).
  marked: MarkedRun = markedRuns(frames),
): () => void {
  async function onMessage(e: MessageEvent) {
    const source = frames().find((f) => f && e.source === f.contentWindow)
    if (!source) return
    const reply = (message: unknown) => source.contentWindow?.postMessage(message, '*')
    const snap = parseSnapshotResult(e.data)
    if (snap) return handlers.onSnapshot(snap, source)
    const widget = parseWidgetRequest(e.data)
    if (widget) {
      const answer = await handlers.onWidget(widget)
      if (answer) reply(answer)
      return
    }
    const rejected = rejectedWidgetReply(e.data)
    if (rejected) return reply(rejected)
    const values = parseParamsRequest(e.data)
    if (!values) return
    await marked(() => handlers.onSetParams(values))
  }
  window.addEventListener('message', onMessage)
  return () => window.removeEventListener('message', onMessage)
}
