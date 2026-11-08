// The editing state of a numberSetting.ts setting: a draft applied on blur or
// Enter, flushed to the session before `value` changes, since the backend
// reads the setting from the session on the next request.

import { useRef, useState } from 'react'
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
  // What is saved, ahead of `value`, which follows once the session has it.
  const saved = useRef(value)

  async function apply() {
    const typed = parseNumber(draft)
    if (typed === null) return setDraft(String(saved.current))
    const next = saveNumber(setting, typed)
    setDraft(String(next))
    if (next === saved.current) return
    saved.current = next
    await flushPatches()
    setValue(next)
  }

  return { value, draft, setDraft, apply }
}
