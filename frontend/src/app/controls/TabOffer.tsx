import { useEffect } from 'react'

// A tab the agent opened (docs/remote.md#tabs): the session to show, its name
// and the link that claims it.
export type TabOpen = { session: string; label: string; url: string }

// Shown when the browser refused to open the tab by itself; the button is the
// click it wanted. Gone after a minute, with the push parked for the tab.
export function TabOffer({ offer, onDone }: { offer: TabOpen | null; onDone: () => void }) {
  useEffect(() => {
    if (!offer) return
    const t = window.setTimeout(onDone, 60_000)
    return () => window.clearTimeout(t)
  }, [offer, onDone])
  if (!offer) return null
  return (
    <div
      data-testid="tab-offer"
      className="fixed bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-3 rounded-md bg-slate-800/90 px-4 py-2 text-sm text-slate-100 shadow-lg ring-1 ring-white/10"
    >
      Agent opened {offer.label}
      <button
        type="button"
        data-testid="tab-offer-open"
        onClick={() => {
          window.open(offer.url, offer.session)
          onDone()
        }}
        className="glass-btn px-2 py-1 text-xs font-medium text-indigo-200"
      >
        Open
      </button>
    </div>
  )
}
