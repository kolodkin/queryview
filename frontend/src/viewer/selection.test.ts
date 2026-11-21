import { describe, expect, test } from 'vitest'
import { pickSelection, selectionSearch } from './selection'

const CONNS = ['sales', 'ops']
const DASHES = ['revenue', 'churn']
const NONE = { connection: null, dashboard: null }

describe('pickSelection', () => {
  test('the URL wins, so a shared link opens what it names', () => {
    const stored = { connection: 'sales', dashboard: 'churn' }
    expect(pickSelection('?connection=ops&name=revenue', stored, CONNS, DASHES)).toEqual({
      connection: 'ops',
      dashboard: 'revenue',
    })
  })

  test('without a URL the last pick reopens', () => {
    const stored = { connection: 'ops', dashboard: 'churn' }
    expect(pickSelection('', stored, CONNS, DASHES)).toEqual({
      connection: 'ops',
      dashboard: 'churn',
    })
  })

  test('with neither, the first connection and no dashboard', () => {
    expect(pickSelection('', NONE, CONNS, DASHES)).toEqual({ connection: 'sales', dashboard: '' })
  })

  test('a stored pick that is gone falls back', () => {
    const stored = { connection: 'retired', dashboard: 'deleted' }
    expect(pickSelection('', stored, CONNS, DASHES)).toEqual({ connection: 'sales', dashboard: '' })
  })

  test('a URL connection that is gone falls back to the last pick, then the first', () => {
    const stored = { connection: 'ops', dashboard: null }
    expect(pickSelection('?connection=retired', stored, CONNS, DASHES).connection).toBe('ops')
    expect(pickSelection('?connection=retired', NONE, CONNS, DASHES).connection).toBe('sales')
  })

  test('a URL dashboard is kept even when unknown, so the page can say it is not found', () => {
    expect(pickSelection('?name=gone', NONE, CONNS, DASHES).dashboard).toBe('gone')
  })

  test('each half is picked on its own', () => {
    const stored = { connection: 'ops', dashboard: 'churn' }
    expect(pickSelection('?name=revenue', stored, CONNS, DASHES)).toEqual({
      connection: 'ops',
      dashboard: 'revenue',
    })
    expect(pickSelection('?connection=sales', stored, CONNS, DASHES)).toEqual({
      connection: 'sales',
      dashboard: 'churn',
    })
  })

  test('no connections at all is an empty pick, not a crash', () => {
    expect(pickSelection('', NONE, [], [])).toEqual({ connection: '', dashboard: '' })
  })
})

describe('selectionSearch', () => {
  test('is the query string a pick is shared as', () => {
    expect(selectionSearch({ connection: 'sales', dashboard: 'ops/eu report' })).toBe(
      '?connection=sales&name=ops%2Feu+report',
    )
    expect(selectionSearch({ connection: 'sales', dashboard: '' })).toBe('?connection=sales')
    expect(selectionSearch({ connection: '', dashboard: '' })).toBe('')
  })

  test('round-trips through pickSelection', () => {
    const sel = { connection: 'ops', dashboard: 'a&b=c' }
    expect(pickSelection(selectionSearch(sel), NONE, CONNS, ['a&b=c'])).toEqual(sel)
  })
})
