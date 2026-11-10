// A tab the agent opened (docs/remote.md#tabs): the session to show, its name
// and the link that claims it.
export type TabOpen = { session: string; label: string; url: string }

// Shown when the browser refused to open a tab by itself; the button is the
// click it wanted. The shell drops each after a minute, with its parked push.
export function TabOffers({
  offers,
  onDone,
}: {
  offers: TabOpen[]
  onDone: (session: string) => void
}) {
  if (offers.length === 0) return null
  return (
    <div className="fixed bottom-4 left-1/2 flex -translate-x-1/2 flex-col gap-2">
      {offers.map((offer) => (
        <TabOffer key={offer.session} offer={offer} onDone={() => onDone(offer.session)} />
      ))}
    </div>
  )
}

function TabOffer({ offer, onDone }: { offer: TabOpen; onDone: () => void }) {
  return (
    <div
      data-testid="tab-offer"
      className="flex items-center gap-3 rounded-md bg-slate-800/90 px-4 py-2 text-sm text-slate-100 shadow-lg ring-1 ring-white/10"
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
