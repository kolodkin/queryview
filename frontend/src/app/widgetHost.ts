// The app's side of the dashboard widget channel: run the query a
// <qv-select-view> named, on the session's connection. The frame sent a name
// and values only; the SQL is the dashboard's own, resolved by the caller.

import type { WidgetReply, WidgetRequest } from '../core'
import { apiFetch } from './api'
import { downloadText } from './yamlio'

// The SQL to run for a query name, or why it can't run.
export type WidgetSql = { sql: string } | { message: string }

async function post(path: string, body: unknown): Promise<Record<string, unknown>> {
  try {
    const res = await apiFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return await res.json()
  } catch {
    return { ok: false, message: 'request failed' }
  }
}

// Answer one widget request; null when there is nothing to post back (CSV).
export async function answerWidget(
  req: WidgetRequest,
  sqlFor: (query: string) => WidgetSql,
): Promise<WidgetReply | null> {
  const resolved = sqlFor(req.query)
  const failed = (message: string): WidgetReply | null =>
    req.type === 'widget-csv'
      ? null
      : {
          type: req.type === 'widget-query' ? 'widget-result' : 'widget-fields',
          id: req.id,
          ok: false,
          message,
        }
  if ('message' in resolved) return failed(resolved.message)
  const query = resolved.sql

  if (req.type === 'widget-describe') {
    const d = await post('/api/db/describe', { query })
    if (!d.ok) return failed(String(d.message ?? 'describe failed'))
    return { type: 'widget-fields', id: req.id, ok: true, fields: (d.fields ?? []) as never }
  }

  const page = { query, limit: req.limit, offset: req.offset, order_by: req.orderBy }
  if (req.type === 'widget-csv') {
    const d = await post('/api/db/query', { ...page, format: 'csv' })
    if (d.ok) downloadText('query.csv', String(d.output ?? ''), 'text/csv')
    return null
  }
  const d = await post('/api/db/query', page)
  if (!d.ok) return failed(String(d.message ?? 'query failed'))
  return {
    type: 'widget-result',
    id: req.id,
    ok: true,
    meta: (d.meta ?? []) as never,
    data: (d.data ?? []) as never,
  }
}
