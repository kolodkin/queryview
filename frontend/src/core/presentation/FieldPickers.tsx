// "Fields" / "Order by" dropdowns shared by the query panel and explorer.
// Field toggles only change client-side column visibility; order-by changes
// go to the parent, which decides when to re-run the query.

import { useMemo, useState } from 'react'

import { filterNames } from '../nameFilter'
import { useDismiss } from '../useDismiss'

export type Field = { name: string; type: string }

export type OrderCol = { name: string; dir: 'ASC' | 'DESC' }

type MenuProps = {
  testid: string
  fields: Field[]
  isOn: (name: string) => boolean
  onToggle: (name: string) => void
  itemTestid: string
  headerExtra?: React.ReactNode
}

// A trigger button plus a searchable checklist popover of fields.
function FieldMenu({ label, ...panel }: MenuProps & { label: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const ref = useDismiss<HTMLDivElement>(open, () => setOpen(false))
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        data-testid={panel.testid}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={`glass-toggle flex items-center gap-1.5 px-2.5 py-1 text-xs ${open ? 'is-active-soft' : ''}`}
      >
        {label}
        <span className="text-slate-400">▾</span>
      </button>
      {open && <FieldMenuPanel {...panel} />}
    </div>
  )
}

// Mounted only while open, so the search starts blank on each open.
function FieldMenuPanel({ testid, fields, isOn, onToggle, itemTestid, headerExtra }: MenuProps) {
  const [filter, setFilter] = useState('')
  const visible = filterNames(fields, filter, (f) => f.name)
  return (
    <div
      data-testid={`${testid}-panel`}
      className="glass-popover absolute left-0 top-full z-20 mt-2 flex max-h-80 w-72 flex-col p-1 text-sm"
    >
      <div className="flex items-center gap-1 p-1">
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={`Search ${fields.length} fields…`}
          aria-label="Search fields"
          data-testid={`${testid}-filter`}
          autoFocus
          autoComplete="off"
          className="glass-input min-w-0 flex-1 px-2 py-1 text-sm"
        />
        {headerExtra}
      </div>
      <div role="listbox" aria-multiselectable className="overflow-auto">
        {visible.map((f) => {
          const on = isOn(f.name)
          return (
            <button
              key={f.name}
              type="button"
              role="option"
              aria-selected={on}
              onClick={() => onToggle(f.name)}
              data-testid={itemTestid}
              data-col={f.name}
              data-on={on}
              title={f.type}
              className="flex w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-white/10"
            >
              <span
                className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border text-[10px] leading-none ${
                  on ? 'border-indigo-400 bg-indigo-500 text-white' : 'border-white/25'
                }`}
              >
                {on ? '✓' : ''}
              </span>
              <span className={`truncate ${on ? 'text-indigo-100' : 'text-slate-300'}`}>
                {f.name}
              </span>
              <span className="ml-auto shrink-0 truncate font-mono text-[10px] text-slate-500">
                {f.type}
              </span>
            </button>
          )
        })}
        {visible.length === 0 && (
          <p className="px-2 py-1.5 text-slate-400">No fields match “{filter.trim()}”.</p>
        )}
      </div>
    </div>
  )
}

export function FieldPickers({
  fields,
  visibleCols,
  orderBy,
  onVisibleColsChange,
  onOrderByChange,
  trailing,
}: {
  fields: Field[]
  visibleCols: string[]
  orderBy: OrderCol[]
  onVisibleColsChange: (cols: string[]) => void
  onOrderByChange: (order: OrderCol[]) => void
  // Rendered after the order-by chips (e.g. the query panel's Run button).
  trailing?: React.ReactNode
}) {
  function toggleField(name: string) {
    onVisibleColsChange(
      visibleCols.includes(name)
        ? visibleCols.filter((c) => c !== name)
        : [...visibleCols, name],
    )
  }

  function toggleOrder(name: string) {
    onOrderByChange(
      orderBy.some((o) => o.name === name)
        ? orderBy.filter((o) => o.name !== name)
        : [...orderBy, { name, dir: 'ASC' }],
    )
  }

  function flipDir(name: string) {
    onOrderByChange(
      orderBy.map((o) =>
        o.name === name ? { ...o, dir: o.dir === 'ASC' ? 'DESC' : 'ASC' } : o,
      ),
    )
  }

  const visible = useMemo(() => new Set(visibleCols), [visibleCols])
  const isVisible = (name: string) => visible.has(name)
  const shown = fields.filter((f) => isVisible(f.name)).length

  return (
    <div
      data-testid="field-pickers"
      className="flex flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2"
    >
      <FieldMenu
        testid="fields-menu"
        label={
          <>
            <span className="font-medium text-slate-200">Fields</span>
            <span data-testid="fields-count" className="text-slate-400">
              {shown}/{fields.length}
            </span>
          </>
        }
        fields={fields}
        isOn={isVisible}
        onToggle={toggleField}
        itemTestid="field-toggle"
        headerExtra={
          <>
            <button
              type="button"
              data-testid="fields-select-all"
              onClick={() => onVisibleColsChange(fields.map((f) => f.name))}
              className="glass-btn shrink-0 px-2 py-1 text-xs"
            >
              All
            </button>
            <button
              type="button"
              data-testid="fields-clear"
              onClick={() => onVisibleColsChange([])}
              className="glass-btn shrink-0 px-2 py-1 text-xs"
            >
              None
            </button>
          </>
        }
      />

      <FieldMenu
        testid="orderby-menu"
        label={<span className="font-medium text-slate-200">Order by</span>}
        fields={fields}
        isOn={(name) => orderBy.some((o) => o.name === name)}
        onToggle={toggleOrder}
        itemTestid="orderby-add"
      />

      {orderBy.map((o, i) => (
        <span
          key={o.name}
          data-testid="orderby-chip"
          data-col={o.name}
          className="flex items-center gap-1 rounded-md border border-indigo-400/40 bg-white/[0.06] px-2 py-0.5 text-xs"
        >
          <span className="text-slate-400">{i + 1}.</span>
          <span className="font-medium">{o.name}</span>
          <button
            type="button"
            data-testid="orderby-dir"
            onClick={() => flipDir(o.name)}
            className="rounded bg-white/10 px-1.5 py-0.5 font-mono hover:bg-white/20"
          >
            {o.dir}
          </button>
          <button
            type="button"
            data-testid="orderby-remove"
            onClick={() => toggleOrder(o.name)}
            aria-label={`remove ${o.name}`}
            className="text-slate-400 hover:text-red-400"
          >
            ×
          </button>
        </span>
      ))}
      {trailing}
    </div>
  )
}
