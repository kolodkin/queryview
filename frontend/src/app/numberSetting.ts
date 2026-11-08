// A whole-number setting kept in the session's `ui` blob (session.ts holds the
// storage shape): the Explorer's Max entries, the header's Query timeout.
// useNumberSetting.ts and NumberInput.tsx edit one.

import { patchView, viewState } from './session'

export type NumberSetting = { view: string; key: string; fallback: number; max: number }

export function loadNumber(s: NumberSetting): number {
  const stored = viewState(s.view)[s.key]
  return typeof stored === 'number' ? stored : s.fallback
}

// The typed value, or null for a blank or non-number field (keep the current one).
export function parseNumber(draft: string): number | null {
  const n = Number(draft)
  return draft.trim() !== '' && Number.isFinite(n) ? n : null
}

// Saves the value clamped to a whole number in 1..max and returns it.
export function saveNumber(s: NumberSetting, n: number): number {
  const clamped = Number.isFinite(n) ? Math.min(s.max, Math.max(1, Math.round(n))) : s.fallback
  patchView(s.view, { [s.key]: clamped })
  return clamped
}
