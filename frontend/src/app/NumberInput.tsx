// The field for a numberSetting.ts setting; useNumberSetting.ts holds its state.

import type { NumberField } from './useNumberSetting'

export function NumberInput({
  field,
  testid,
  className,
}: {
  field: NumberField
  testid: string
  className: string
}) {
  return (
    <input
      type="number"
      min={1}
      data-testid={testid}
      value={field.draft}
      onChange={(e) => field.setDraft(e.target.value)}
      onBlur={() => void field.apply()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
      }}
      className={`glass-input px-1.5 py-0.5 text-xs ${className}`}
    />
  )
}
