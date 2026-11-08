// The editing state of a numberSetting.ts setting: a draft applied on blur or
// Enter, flushed to the session before `value` changes, since the backend
// reads the setting from the session on the next request.

import { useState } from 'react'
import { loadNumber, parseNumber, saveNumber, type NumberSetting } from './numberSetting'
import { flushPatches } from './session'

export type NumberField = {
  value: number
  draft: string
  setDraft: (draft: string) => void
  apply: () => Promise<void>
}

export function useNumberSetting(setting: NumberSetting): NumberField {
  const [value, setValue] = useState(() => loadNumber(setting))
  const [draft, setDraft] = useState(String(value))

  async function apply() {
    const typed = parseNumber(draft)
    if (typed === null) return setDraft(String(value))
    const next = saveNumber(setting, typed)
    setDraft(String(next))
    if (next === value) return
    await flushPatches()
    setValue(next)
  }

  return { value, draft, setDraft, apply }
}
