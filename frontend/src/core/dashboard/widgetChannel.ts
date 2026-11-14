// The widget half of the dashboard frame channel (docs/dashboard.md, "Widgets").
// A `<qv-select-view>` in the frame names one of the dashboard's queries and
// sends values only; the host substitutes and runs the dashboard's own SQL.

import type { Field, OrderCol } from '../presentation/FieldPickers'
import type { Cell, ColumnMeta } from '../results/rows'

export type WidgetRequest =
  | {
      type: 'widget-query'
      id: string
      query: string
      limit: number
      offset: number
      orderBy: OrderCol[]
    }
  | { type: 'widget-describe'; id: string; query: string }
  | { type: 'widget-csv'; query: string; limit: number; offset: number; orderBy: OrderCol[] }

export type WidgetReply =
  | { type: 'widget-result'; id: string; ok: true; meta: ColumnMeta[]; data: Cell[][] }
  | { type: 'widget-result'; id: string; ok: false; message: string }
  | { type: 'widget-fields'; id: string; ok: true; fields: Field[] }
  | { type: 'widget-fields'; id: string; ok: false; message: string }

// The backend clamps to this too; rejecting here keeps a forged message from
// reaching it at all.
const MAX_LIMIT = 1000

function parseOrderBy(raw: unknown): OrderCol[] | null {
  if (!Array.isArray(raw)) return null
  const out: OrderCol[] = []
  for (const o of raw) {
    if (!o || typeof o !== 'object') return null
    const { name, dir } = o as Record<string, unknown>
    if (typeof name !== 'string' || name === '') return null
    if (dir !== 'ASC' && dir !== 'DESC') return null
    out.push({ name, dir })
  }
  return out
}

// A widget message from the frame, or null for anything else or anything
// malformed. Never carries SQL: `query` is a name the host looks up.
export function parseWidgetRequest(data: unknown): WidgetRequest | null {
  if (typeof data !== 'object' || data === null) return null
  const m = data as Record<string, unknown>
  if (typeof m.query !== 'string' || m.query === '') return null
  if (m.type === 'widget-describe') {
    return typeof m.id === 'string' ? { type: m.type, id: m.id, query: m.query } : null
  }
  if (m.type !== 'widget-query' && m.type !== 'widget-csv') return null
  const { limit, offset } = m
  if (!Number.isInteger(limit) || (limit as number) < 1 || (limit as number) > MAX_LIMIT)
    return null
  if (!Number.isInteger(offset) || (offset as number) < 0) return null
  const orderBy = parseOrderBy(m.order_by)
  if (!orderBy) return null
  const page = { query: m.query, limit: limit as number, offset: offset as number, orderBy }
  if (m.type === 'widget-csv') return { type: m.type, ...page }
  return typeof m.id === 'string' ? { type: m.type, id: m.id, ...page } : null
}

// The answer to a widget message that failed parseWidgetRequest, so the widget
// waiting on that id shows an error instead of hanging; null when the message
// isn't an identifiable widget request.
export function rejectedWidgetReply(data: unknown): WidgetReply | null {
  if (typeof data !== 'object' || data === null) return null
  const { type, id } = data as Record<string, unknown>
  if (typeof id !== 'string') return null
  if (type === 'widget-query')
    return { type: 'widget-result', id, ok: false, message: 'Bad request' }
  if (type === 'widget-describe')
    return { type: 'widget-fields', id, ok: false, message: 'Bad request' }
  return null
}

// The queries `<qv-select-view>` tags own, distinct and in order. The host
// leaves these out of the up-front run: each runs for its widget alone.
export function widgetQueryNames(html: string): string[] {
  const names = new Set<string>()
  for (const m of html.matchAll(/<qv-select-view\b[^>]*?\bquery=(?:"([^"]*)"|'([^']*)')/g)) {
    const name = m[1] ?? m[2]
    if (name) names.add(name)
  }
  return [...names]
}

// `order-by="day desc, name"`: comma-separated columns, ASC unless `desc`.
export function parseOrderByAttr(attr: string | null): OrderCol[] {
  return parseFieldsAttr(attr).map((part) => {
    const m = /^(.*?)(?:\s+(asc|desc))?$/i.exec(part)!
    return { name: m[1], dir: m[2]?.toUpperCase() === 'DESC' ? 'DESC' : 'ASC' }
  })
}

// `fields="day, revenue"`: the columns shown at first.
export function parseFieldsAttr(attr: string | null): string[] {
  return (attr ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}
