import { useCopy } from '../../core'

// Copies a name (database, table) without picking its row; dim until the row
// — a `group` — is hovered. A sibling of the row's button, not a child.
export function CopyName({ name, testid }: { name: string; testid: string }) {
  const [copied, copy] = useCopy()
  return (
    <button
      type="button"
      data-testid={testid}
      aria-label={`Copy ${name}`}
      title={copied ? 'Copied' : 'Copy name'}
      onClick={() => void copy(name)}
      className="shrink-0 rounded px-2 py-1.5 text-xs text-slate-500 group-hover:text-slate-300 hover:!text-indigo-200"
    >
      {copied ? (
        '✓'
      ) : (
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="9" width="11" height="11" rx="2" />
          <path d="M5 15V5a2 2 0 0 1 2-2h10" />
        </svg>
      )}
    </button>
  )
}
