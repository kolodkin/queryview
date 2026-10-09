import { describe, expect, it } from 'vitest'

import { resultSummary, runnableText } from './sqlScript'

describe('runnableText', () => {
  it('runs the selection when there is one, else everything', () => {
    expect(runnableText('SELECT 1; SELECT 2', 10, 18)).toBe('SELECT 2')
    expect(runnableText('SELECT 1; SELECT 2', 4, 4)).toBe('SELECT 1; SELECT 2')
  })
  it('ignores a whitespace-only selection', () => {
    expect(runnableText('SELECT 1;  SELECT 2', 9, 11)).toBe('SELECT 1;  SELECT 2')
  })
})

describe('resultSummary', () => {
  it('counts rows', () => {
    expect(resultSummary({ ok: true, meta: [], data: [[1], [2]], truncated: false, status: '', message: '', elapsed_ms: 12, sql: '' })).toBe('2 rows · 12 ms')
    expect(resultSummary({ ok: true, meta: [], data: [[1]], truncated: false, status: '', message: '', elapsed_ms: 0, sql: '' })).toBe('1 row · 0 ms')
  })
  it('says when the rows were capped', () => {
    expect(resultSummary({ ok: true, meta: [], data: Array(1000).fill([1]), truncated: true, status: '', message: '', elapsed_ms: 5, sql: '' })).toBe('first 1000 rows, more exist · 5 ms')
  })
  it('shows the driver status for statements without rows', () => {
    expect(resultSummary({ ok: true, meta: null, data: null, truncated: false, status: 'INSERT 0 3', message: '', elapsed_ms: 3, sql: '' })).toBe('INSERT 0 3 · 3 ms')
  })
  it('shows the error for a failed statement', () => {
    expect(resultSummary({ ok: false, meta: null, data: null, truncated: false, status: '', message: 'boom', elapsed_ms: 1, sql: '' })).toBe('boom')
  })
})
