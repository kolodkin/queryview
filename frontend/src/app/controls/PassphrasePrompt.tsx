import { useState, type FormEvent } from 'react'

// A modal asking for a locked connection's passphrase (docs/connect.md#locked-connections).
// `onSubmit` resolves to an error message to show, or null when done — the
// caller closes the prompt by unmounting it.
export function PassphrasePrompt({
  title,
  action,
  onSubmit,
  onCancel,
  cancelLabel = 'Cancel',
}: {
  title: string
  action: string
  onSubmit: (passphrase: string) => Promise<string | null>
  onCancel: () => void
  cancelLabel?: string
}) {
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!value || busy) return
    setBusy(true)
    const err = await onSubmit(value)
    setBusy(false)
    if (err) setError(err)
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid="passphrase-prompt"
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-6 backdrop-blur-sm"
    >
      <form onSubmit={submit} className="glass-popover w-80 space-y-3 p-5 text-sm">
        <p className="font-medium text-slate-100">{title}</p>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoFocus
          autoComplete="off"
          aria-label="Passphrase"
          placeholder="Passphrase"
          data-testid="passphrase-input"
          className="glass-input w-full px-3 py-2"
        />
        {error && (
          <p data-testid="passphrase-error" className="text-red-300">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy || !value}
            data-testid="passphrase-submit"
            className="glass-btn-primary px-3 py-1.5"
          >
            {action}
          </button>
          <button
            type="button"
            onClick={onCancel}
            data-testid="passphrase-cancel"
            className="glass-btn px-3 py-1.5"
          >
            {cancelLabel}
          </button>
        </div>
      </form>
    </div>
  )
}
