import { NOTICE_CLASS } from './Toast'

// A tab the agent opened (docs/remote.md#tabs): the session to show, its name
// and the link that claims it.
export type TabOpen = { session: string; label: string; url: string }

// Shown when the browser refused to open a tab by itself; the button is the
// click it wanted, and `onOpen` the shell's opener. The shell drops each after
// a minute, with its queued push.
export function TabOffers({
  offers,
  onOpen,
}: {
  offers: TabOpen[]
  onOpen: (offer: TabOpen) => void
}) {
  if (offers.length === 0) return null
  return (
    <div className="fixed bottom-4 left-1/2 flex -translate-x-1/2 flex-col gap-2">
      {offers.map((offer) => (
        <div
          key={offer.session}
          data-testid="tab-offer"
          className={`flex items-center gap-3 ${NOTICE_CLASS}`}
        >
          Agent opened {offer.label}
          <button
            type="button"
            data-testid="tab-offer-open"
            onClick={() => onOpen(offer)}
            className="glass-btn px-2 py-1 text-xs font-medium text-indigo-200"
          >
            Open
          </button>
        </div>
      ))}
    </div>
  )
}
