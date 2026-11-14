import yaml from 'js-yaml'

// Selector with choices resolved to a concrete list, substituted into SQL via a
// `{name}` placeholder. See docs/query.md.
export type ParamDef = { name: string; options: string[] }

// Selector declared under the reserved `params:` key in a query's cell_view YAML.
// Exactly one of `options` (static) or `optionsSql` (first column of a query) is set.
export type ParamSpec = {
  name: string
  options?: string[]
  optionsSql?: string
}

// Parse YAML into a plain object, or null on parse error / non-object root.
export function parseYamlObject(text: string | null | undefined): Record<string, unknown> | null {
  if (!text) return null
  let doc: unknown
  try {
    doc = yaml.load(text)
  } catch {
    return null
  }
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return null
  return doc as Record<string, unknown>
}

// Parse the cell_view YAML's `params:` section into selector specs. Defensive: a
// parse error or malformed entry is dropped, so a broken config yields no
// dropdowns rather than breaking the panel. Declaring both options keys drops it.
export function parseQueryParams(text: string | null | undefined): ParamSpec[] {
  const doc = parseYamlObject(text)
  if (!doc) return []
  const raw = doc.params
  if (!Array.isArray(raw)) return []
  const out: ParamSpec[] = []
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue
    const o = entry as Record<string, unknown>
    if (typeof o.name !== 'string' || o.name === '') continue
    const hasOptions = Array.isArray(o.options)
    const sql = typeof o.options_sql === 'string' ? o.options_sql.trim() : ''
    // Mutually exclusive: declaring both keys is ambiguous, so drop the entry.
    if (hasOptions && sql) continue
    if (sql) {
      out.push({ name: o.name, optionsSql: sql })
      continue
    }
    if (hasOptions) {
      // Keep scalars only; null/objects/arrays (all typeof 'object') aren't valid.
      const options = (o.options as unknown[]).filter((v) => typeof v !== 'object').map(String)
      if (options.length === 0) continue
      out.push({ name: o.name, options })
    }
    // Neither a usable options list nor an options_sql query: drop.
  }
  return out
}

// A quoted SQL string literal: single quotes doubled, and backslashes too where
// the dialect reads them as escapes (the connection's backslashEscapes).
export function quoteLiteral(value: string, backslashEscapes: boolean): string {
  const v = backslashEscapes ? value.replaceAll('\\', '\\\\') : value
  return `'${v.replaceAll("'", "''")}'`
}

// Substitute each `{name}` with the selected value as a quoted SQL literal.
// Unselected params fall back to their first option; an unmatched placeholder
// is left untouched.
export function applyParams(
  sql: string,
  defs: ParamDef[],
  values: Record<string, string>,
  backslashEscapes: boolean,
): string {
  let out = sql
  for (const def of defs) {
    const value = values[def.name] ?? def.options[0]
    out = out.replaceAll(`{${def.name}}`, quoteLiteral(value, backslashEscapes))
  }
  return out
}
