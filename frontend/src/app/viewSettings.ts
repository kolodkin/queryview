// Per-view UI settings in localStorage: one key per view (`qv_view_<name>`)
// holding that view's settings as a JSON object, so a view can remember a new
// option without claiming another key. A missing, unparseable or hand-edited
// value reads as "nothing remembered" rather than breaking the page.

const PREFIX = 'qv_view_'

export type ViewSettings = Record<string, unknown>

export function loadViewSettings(view: string): ViewSettings {
  try {
    const raw = localStorage.getItem(PREFIX + view)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    return parsed as ViewSettings
  } catch {
    return {}
  }
}

// Merge into the view's stored object, leaving settings this build doesn't know
// about intact.
export function patchViewSettings(view: string, changes: ViewSettings): void {
  try {
    const next = { ...loadViewSettings(view), ...changes }
    localStorage.setItem(PREFIX + view, JSON.stringify(next))
  } catch {
    /* non-persistent contexts still work within the page's lifetime */
  }
}
