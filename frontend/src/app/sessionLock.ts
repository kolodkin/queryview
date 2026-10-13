// Fire-and-forget edit-lock control for the live session. The lock is advisory
// (the backend TTL-expires it), so failures are swallowed.
import { useEffect, type RefObject } from 'react'

import { apiFetch } from './api'
import { flushPatches } from './session'

export async function postLock(sessionId: string, action: 'acquire' | 'release'): Promise<void> {
  if (!sessionId) return
  try {
    await apiFetch('/api/remote/lock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, action }),
    })
  } catch {
    /* advisory lock: ignore transport errors */
  }
}

// Leaving the panel is what "done editing" means. One exit detector serves
// both consumers of that signal, so they cannot disagree: the session write
// lands then (not on a timer while you are still typing), and the edit lock,
// when armed, is released. The lock is acquired on focus and refreshed every
// ~10s against its 30s TTL. Advisory — postLock swallows errors.
export function useEditLock(
  ref: RefObject<HTMLElement | null>,
  remoteId: string | null | undefined,
): void {
  useEffect(() => {
    const el = ref.current
    if (!el) return
    let exitTimer: number | undefined
    // Focus is (or just was) inside: an unmount must still do the exit.
    let held = false
    const acquire = () => {
      if (remoteId) void postLock(remoteId, 'acquire')
    }
    const exit = () => {
      held = false
      void flushPatches()
      if (remoteId) void postLock(remoteId, 'release')
    }
    const onFocusIn = () => {
      window.clearTimeout(exitTimer)
      held = true
      acquire()
    }
    const onFocusOut = () => {
      // Moving between inputs fires focusout then focusin; only a real exit
      // counts.
      window.clearTimeout(exitTimer)
      exitTimer = window.setTimeout(() => {
        if (!el.contains(document.activeElement)) exit()
      }, 150)
    }
    el.addEventListener('focusin', onFocusIn)
    el.addEventListener('focusout', onFocusOut)
    const beat = remoteId
      ? window.setInterval(() => {
          if (el.contains(document.activeElement)) acquire()
        }, 10000)
      : undefined
    return () => {
      el.removeEventListener('focusin', onFocusIn)
      el.removeEventListener('focusout', onFocusOut)
      window.clearInterval(beat)
      window.clearTimeout(exitTimer)
      // Navigating away unmounts before the exit timer fires.
      if (held) exit()
    }
  }, [ref, remoteId])
}
