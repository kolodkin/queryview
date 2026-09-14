// Busy indicators: Spinner is the bare glyph, Loading the labelled block a
// panel shows while its first payload is in flight.

export function Spinner({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg
      className={`animate-spin text-indigo-300 ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path
        d="M22 12a10 10 0 0 0-10-10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function Loading({ label, testid }: { label: string; testid?: string }) {
  return (
    <div
      data-testid={testid}
      role="status"
      className="flex items-center gap-2 py-2 text-sm text-slate-400"
    >
      <Spinner />
      {label}
    </div>
  )
}
