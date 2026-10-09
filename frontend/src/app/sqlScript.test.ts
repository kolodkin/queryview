import { describe, expect, it } from 'vitest'

import { resultSummary, runSummary, statementAt, type StatementResult } from './sqlScript'

const base: StatementResult = {
  ok: true,
  meta: [],
  data: null,
  truncated: false,
  status: '',
  message: '',
  elapsed_ms: 0,
  sql: '',
}

describe('statementAt', () => {
  const text = 'SELECT 1;\n\nSELECT \'a;b\' -- c;\n  ;SELECT 3'
  it('picks the statement the cursor is inside', () => {
    expect(statementAt(text, 3)).toBe('SELECT 1')
    expect(statementAt(text, 15)).toBe("SELECT 'a;b' -- c;")
    expect(statementAt(text, text.length)).toBe('SELECT 3')
  })
  it('keeps the statement when the cursor sits right after its semicolon', () => {
    expect(statementAt(text, 9)).toBe('SELECT 1')
  })
  it('moves to the next statement from a blank line between two', () => {
    expect(statementAt(text, 10)).toBe("SELECT 'a;b' -- c;")
  })
  it('falls back to the last statement after trailing whitespace', () => {
    expect(statementAt('SELECT 1;\n\n', 11)).toBe('SELECT 1')
    expect(statementAt('   ', 1)).toBe('')
  })
})

describe('resultSummary', () => {
  it('counts rows', () => {
    expect(resultSummary({ ...base, data: [[1], [2]], elapsed_ms: 12 })).toBe('2 rows · 12 ms')
    expect(resultSummary({ ...base, data: [[1]] })).toBe('1 row · 0 ms')
  })
  it('says when the rows were capped', () => {
    expect(resultSummary({ ...base, data: Array(100).fill([1]), truncated: true, elapsed_ms: 5 })).toBe(
      'first 100 rows, more exist · 5 ms',
    )
  })
  it('shows the driver status for statements without rows', () => {
    expect(resultSummary({ ...base, meta: null, status: 'INSERT 0 3', elapsed_ms: 3 })).toBe('INSERT 0 3 · 3 ms')
  })
  it('shows the error for a failed statement', () => {
    expect(resultSummary({ ...base, ok: false, meta: null, message: 'boom' })).toBe('boom')
  })
})

describe('runSummary', () => {
  it('is the statement summary for a single statement', () => {
    expect(runSummary([{ ...base, data: [[1], [2]], elapsed_ms: 2 }])).toEqual({ ok: true, text: '2 rows · 2 ms' })
  })
  it('counts the statements and the total time, with the last rows', () => {
    const run = [
      { ...base, meta: null, status: 'OK', elapsed_ms: 3 },
      { ...base, meta: null, status: 'INSERT 0 2', elapsed_ms: 1 },
      { ...base, data: [[1], [2]], elapsed_ms: 2 },
    ]
    expect(runSummary(run)).toEqual({ ok: true, text: '3 statements · 2 rows · 6 ms' })
    expect(runSummary(run.slice(0, 2))).toEqual({ ok: true, text: '2 statements · INSERT 0 2 · 4 ms' })
  })
  it('names the failing statement, its error and a snippet of it', () => {
    const run = [
      { ...base, meta: null, status: 'OK', elapsed_ms: 3 },
      { ...base, ok: false, meta: null, message: 'no such table', sql: 'SELECT *\n  FROM nope' },
    ]
    expect(runSummary(run)).toEqual({
      ok: false,
      text: 'Statement 2 failed: no such table — SELECT * FROM nope',
    })
  })
  it('handles an empty run', () => {
    expect(runSummary([])).toEqual({ ok: true, text: 'Nothing to run' })
  })
})
