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
  // The frame's answer to a snapshot request.
  onSnapshot(result: SnapshotResult): void
  // A widget's request; the reply is posted back to it (null: nothing to post).
  onWidget(req: WidgetRequest): Promise<WidgetReply | null>
  // The page's setParams, values only; resolves to the params-results message.
  onSetParams(values: Record<string, string>): Promise<Record<string, unknown>>
}

// Dispatch the dashboard frame's messages to `handlers`, ignoring every other
// window: the page sends values and names only, never SQL. Returns the
// unsubscribe.
export function listenToFrame(
  frame: () => HTMLIFrameElement | null,
  handlers: FrameHandlers,
): () => void {
  async function onMessage(e: MessageEvent) {
    const target = frame()
    if (!target || e.source !== target.contentWindow) return
    const reply = (message: unknown) => target.contentWindow?.postMessage(message, '*')
    const snap = parseSnapshotResult(e.data)
    if (snap) return handlers.onSnapshot(snap)
    const widget = parseWidgetRequest(e.data)
    if (widget) {
      const answer = await handlers.onWidget(widget)
      if (answer) reply(answer)
      return
    }
    const rejected = rejectedWidgetReply(e.data)
    if (rejected) return reply(rejected)
    const values = parseParamsRequest(e.data)
    if (values) reply(await handlers.onSetParams(values))
  }
  window.addEventListener('message', onMessage)
  return () => window.removeEventListener('message', onMessage)
}
