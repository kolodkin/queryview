import { TEXTAREA_SIZES } from '../textareaSizes'

// The height step buttons; each gets the test id `<testid>-<label>`.
export default function TextareaSizes({
  rows,
  onChange,
  testid,
  className = 'flex items-center justify-end gap-1',
}: {
  rows: number
  onChange: (rows: number) => void
  testid: string
  className?: string
}) {
  return (
    <div className={className}>
      {TEXTAREA_SIZES.map(([label, n]) => (
        <button
          key={label}
          type="button"
          onClick={() => onChange(n)}
          data-testid={`${testid}-${label.toLowerCase()}`}
          className={`glass-toggle px-2 py-1 text-xs ${rows === n ? 'is-active' : ''}`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
