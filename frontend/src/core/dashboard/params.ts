// Dashboard-level selectors, declared in a dashboard's `params` and substituted
// into its queries via `{name}` placeholders. The backend parses the
// declaration, resolves each selector's options and substitutes
// (backend/queryview/dashboard_params.py); this side only shapes the values it
// posts. See docs/system/dashboard.md, "Dashboard parameters".

export type ParamKind = 'value' | 'identifier' | 'dimension' | 'text' | 'each'

// A selector with its option list resolved and a value chosen (or left empty) —
// what the page receives as `window.params`.
export type ResolvedParam = {
  name: string
  kind: ParamKind
  options: string[]
  value: string
}

// The longest text a page may send into a query.
export const MAX_TEXT_PARAM = 10_000

// The chosen values, by name: what a run posts.
export function valuesOf(resolved: ResolvedParam[]): Record<string, string> {
  return Object.fromEntries(resolved.map((p) => [p.name, p.value]))
}

// A page's set-params values, plus each text it left out: what was typed
// survives a change to another selector. A selector left out is not kept — it
// falls back to its default, as an option list may have changed under it.
export function withKeptText(
  values: Record<string, string>,
  resolved: ResolvedParam[],
): Record<string, string> {
  const kept = resolved.filter((p) => p.kind === 'text' && !(p.name in values))
  return { ...values, ...valuesOf(kept) }
}

// A set-params message from the dashboard page: values only, never SQL — the
// SQL lives in the dashboard's queries and is substituted host-side.
export function parseParamsRequest(data: unknown): Record<string, string> | null {
  if (typeof data !== 'object' || data === null) return null
  const msg = data as Record<string, unknown>
  if (msg.type !== 'set-params') return null
  const values = msg.values
  if (typeof values !== 'object' || values === null || Array.isArray(values)) return null
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(values as Record<string, unknown>)) {
    // Checkboxes arrive as booleans; '' (also from null) reads as unset / unchecked.
    out[k] = typeof v === 'boolean' ? (v ? 'on' : '') : String(v ?? '')
  }
  return out
}
