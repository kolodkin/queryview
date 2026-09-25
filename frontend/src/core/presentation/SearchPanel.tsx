// The panel of every searchable dropdown (database menu, field pickers): a
// search box over a filtered option list. Mount it only while open, so the
// search starts blank each time; Enter picks the first match. Dismissal is the
// caller's useDismiss, on the wrapper holding both trigger and panel.

import { useState } from 'react'

import { filterNames } from '../nameFilter'

export function SearchPanel<T>({
  items,
  nameOf,
  noun,
  testid,
  isSelected,
  onPick,
  renderItem,
  itemProps,
  headerExtra,
  className = '',
}: {
  items: T[]
  nameOf: (item: T) => string
  // Plural, for the placeholder and empty state ("databases", "fields").
  noun: string
  // The panel's test id; the search box and empty state get -filter / -empty.
  testid: string
  isSelected: (item: T) => boolean
  onPick: (item: T) => void
  renderItem: (item: T, selected: boolean) => React.ReactNode
  // Extra attributes per option (data-* for tests).
  itemProps?: (item: T) => Record<string, string | boolean>
  // Beside the search box (e.g. All / None).
  headerExtra?: React.ReactNode
  // Placement and width, e.g. "left-0 w-64".
  className?: string
}) {
  const [filter, setFilter] = useState('')
  const visible = filterNames(items, filter, nameOf)
  return (
    <div
      data-testid={testid}
      className={`glass-popover absolute top-full z-10 mt-2 flex max-h-80 flex-col p-1 text-sm ${className}`}
    >
      <form
        className="flex items-center gap-1 p-1"
        onSubmit={(e) => {
          e.preventDefault()
          if (visible.length > 0) onPick(visible[0])
        }}
      >
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={`Search ${items.length} ${noun}…`}
          aria-label={`Search ${noun}`}
          data-testid={`${testid}-filter`}
          autoFocus
          autoComplete="off"
          className="glass-input min-w-0 flex-1 px-2 py-1.5 text-sm"
        />
        {headerExtra}
      </form>
      {visible.length === 0 ? (
        <p className="px-2 py-1.5 text-slate-400" data-testid={`${testid}-empty`}>
          No {noun} match “{filter.trim()}”.
        </p>
      ) : (
        <div role="listbox" className="overflow-auto">
          {visible.map((item) => {
            const selected = isSelected(item)
            return (
              <button
                key={nameOf(item)}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => onPick(item)}
                {...itemProps?.(item)}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-white/10"
              >
                {renderItem(item, selected)}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
