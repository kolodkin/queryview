import { describe, expect, test } from 'vitest'
import { parseParamsRequest, valuesOf, withKeptText, type ResolvedParam } from './params'

// Substitution and option resolution live in the backend
// (backend/queryview/dashboard_params.py); this side only shapes what it posts.

describe('parseParamsRequest', () => {
  test('takes values only, booleans as checkbox state', () => {
    expect(
      parseParamsRequest({ type: 'set-params', values: { a: 'x', d: true, e: false } }),
    ).toEqual({
      a: 'x',
      d: 'on',
      e: '',
    })
    expect(
      parseParamsRequest({ type: 'set-params', values: { n: null, u: undefined, z: 0 } }),
    ).toEqual({ n: '', u: '', z: '0' })
    expect(parseParamsRequest({ type: 'run-queries', queries: {} })).toBeNull()
    expect(parseParamsRequest({ type: 'set-params', values: ['x'] })).toBeNull()
  })
})

describe('the values posted with a run', () => {
  const resolved: ResolvedParam[] = [
    { name: 'note', kind: 'text', options: [], value: 'hi' },
    { name: 'r', kind: 'value', options: ['eu', 'us'], value: 'eu' },
  ]

  test('valuesOf maps names to chosen values', () => {
    expect(valuesOf(resolved)).toEqual({ note: 'hi', r: 'eu' })
  })

  test('a message that leaves a text out keeps what was typed', () => {
    expect(withKeptText({ r: 'us' }, resolved)).toEqual({ r: 'us', note: 'hi' })
  })

  test('a text the message sends, empty included, wins', () => {
    expect(withKeptText({ note: '' }, resolved)).toEqual({ note: '' })
  })

  test('a selector the message leaves out is not kept: it falls back to its default', () => {
    expect(withKeptText({}, resolved)).toEqual({ note: 'hi' })
  })
})
