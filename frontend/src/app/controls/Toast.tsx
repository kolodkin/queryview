import { useEffect } from 'react'

// Transient bottom notice. Renders nothing when message is null; auto-dismisses.
export function Toast({ message, onDone }: { message: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!message) return
    const t = window.setTimeout(onDone, 3000)
    return () => window.clearTimeout(t)
  }, [message, onDone])
  if (!message) return null
  return (
    <div
      data-testid="agent-toast"
      className="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-md bg-slate-800/90 px-4 py-2 text-sm text-slate-100 shadow-lg ring-1 ring-white/10"
    >
      {message}
    </div>
  )
}
