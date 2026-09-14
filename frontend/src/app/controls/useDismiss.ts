import { useEffect, type RefObject } from 'react'

/** Close an open popover the way people expect: a pointer press anywhere
 * outside `ref`, or Escape. Point `ref` at the wrapper that holds *both* the
 * trigger and the panel, so pressing the trigger while open doesn't close here
 * and immediately reopen in the trigger's own click handler. */
export function useDismiss(
  ref: RefObject<HTMLElement | null>,
  open: boolean,
  close: () => void,
) {
  useEffect(() => {
    if (!open) return
    // pointerdown, not click: it fires before focus moves or the click lands,
    // so the panel is gone by the time the outside control reacts.
    const onPointerDown = (e: PointerEvent) => {
      const el = ref.current
      if (el && !el.contains(e.target as Node)) close()
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [ref, open, close])
}
