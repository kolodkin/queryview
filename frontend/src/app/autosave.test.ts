import { describe, expect, test } from 'vitest'
import { queryChanged } from './autosave'

const saved = {
  query: 'SELECT 1',
  cell_view: 'a: {type: text}',
  order_by: [{ name: 'id', dir: 'ASC' as const }],
  fields: ['id'],
}

describe('queryChanged', () => {
  test('a name with no stored row is new', () => {
    expect(queryChanged(undefined, { ...saved })).toBe(true)
  })

  test('identical content needs no write', () => {
    expect(queryChanged(saved, { ...saved })).toBe(false)
  })

  test('null and empty mean the same: nothing stored', () => {
    const bare = { query: 'SELECT 1', cell_view: null, order_by: null, fields: null }
    expect(queryChanged(bare, { query: 'SELECT 1', cell_view: '', order_by: null, fields: null })).toBe(
      false,
    )
  })

  test('any field differing is a change', () => {
    expect(queryChanged(saved, { ...saved, query: 'SELECT 2' })).toBe(true)
    expect(queryChanged(saved, { ...saved, cell_view: '' })).toBe(true)
    expect(queryChanged(saved, { ...saved, order_by: [{ name: 'id', dir: 'DESC' }] })).toBe(true)
    expect(queryChanged(saved, { ...saved, fields: null })).toBe(true)
  })
})
