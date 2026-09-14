// Long-cell support for the results grid: how wide a cell gets before it
// scrolls, and whether its text is serialized JSON/YAML worth showing parsed in
// the cell popup. See docs/query.md, "Long values".

import yaml from 'js-yaml'

// The grid is monospace throughout, so character count is a faithful stand-in
// for rendered width.
export const CELL_WIDTH_CH = 50

export type Structured = { format: 'json' | 'yaml'; data: unknown }

export function isOverflowing(text: string): boolean {
  return text.length > CELL_WIDTH_CH
}

// Only containers are worth a parsed view: a bare scalar renders the same
// either way, so `123` or `"quoted"` is not "structured" here.
function container(data: unknown): boolean {
  return typeof data === 'object' && data !== null
}

// Detect a cell whose *text* is a serialized collection, for the popup's parsed
// view and the `{ }` button glyph.
//
// YAML claims nearly every single-line string (`plain text` is a valid scalar,
// `status: healthy` a valid mapping), so it is tried only on text that already
// spans lines — which keeps prose and Windows paths out. Multi-line prose still
// parses as a folded *scalar*, which the container check rejects.
export function detectStructured(text: string): Structured | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  try {
    const data: unknown = JSON.parse(trimmed)
    if (container(data)) return { format: 'json', data }
  } catch {
    /* not JSON; fall through to YAML */
  }
  if (!trimmed.includes('\n')) return null
  try {
    const data: unknown = yaml.load(trimmed)
    if (container(data)) return { format: 'yaml', data }
  } catch {
    /* not YAML either */
  }
  return null
}
