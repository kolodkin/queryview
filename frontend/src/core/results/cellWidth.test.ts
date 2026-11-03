import { describe, expect, it } from 'vitest'

import { CELL_WIDTH_CH, columnSize, columnsWidth, isOverflowing } from './cellWidth'

describe('isOverflowing', () => {
  it('is false for a value that fits on one line', () => {
    expect(isOverflowing('')).toBe(false)
    expect(isOverflowing('x'.repeat(CELL_WIDTH_CH))).toBe(false)
  })

  it('is true past the cell width', () => {
    expect(isOverflowing('x'.repeat(CELL_WIDTH_CH + 1))).toBe(true)
  })

  // `whitespace-pre` renders these as extra rows however narrow they are, and
  // short multi-line YAML is exactly what the parsed view is for.
  it('is true for multi-line text, even when it is short', () => {
    expect(isOverflowing('id: 1\nname: alpha')).toBe(true)
    expect(isOverflowing('a\nb')).toBe(true)
  })
})

describe('columnSize', () => {
  it('fits the header when the values are shorter', () => {
    expect(columnSize('order_total', ['42', '1200'])).toEqual({
      chars: 'order_total'.length,
      button: false,
    })
  })

  it('fits the widest value when it is longer than the header', () => {
    expect(columnSize('region', ['north', 'regional_summary_rollup'])).toEqual({
      chars: 'regional_summary_rollup'.length,
      button: false,
    })
  })

  it('takes the cap outright when capped, whatever the values', () => {
    expect(columnSize('status', ['ok', 'no'], true)).toEqual({
      chars: CELL_WIDTH_CH,
      button: false,
    })
  })

  it('never shrinks below the floor', () => {
    expect(columnSize('', ['', '']).chars).toBe(3)
    expect(columnSize('', []).chars).toBe(3)
  })

  it('caps at the cell width and notes the button', () => {
    expect(columnSize('id', ['x'.repeat(200)])).toEqual({ chars: CELL_WIDTH_CH, button: true })
  })

  it('measures a multi-line value by its widest line', () => {
    expect(columnSize('doc', ['id: 1\nname: alpha-beta'])).toEqual({
      chars: 'name: alpha-beta'.length,
      button: true,
    })
  })
})

describe('columnsWidth', () => {
  it('adds the padding per column and the button room where there is one', () => {
    expect(columnsWidth([{ chars: 5, button: false }])).toBe('calc(5ch + 1rem)')
    expect(columnsWidth([{ chars: 5, button: true }])).toBe('calc(5ch + 3.25rem)')
    expect(
      columnsWidth([
        { chars: 5, button: false },
        { chars: 50, button: true },
      ]),
    ).toBe('calc(55ch + 4.25rem)')
  })
})
