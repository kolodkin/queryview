import { describe, expect, it } from 'vitest'

import { failedSpan, runSummary, statementRangeAt, type StatementResult } from './queriesScript'

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

describe('statementRangeAt', () => {
  const text = 'SELECT 1;\n\nSELECT \'a;b\' -- c;\n  ;SELECT 3'
  const at = (cursor: number) => {
    const span = statementRangeAt(text, cursor)
    return span && text.slice(span.start, span.end)
  }
  it('picks the statement the cursor is inside', () => {
    expect(at(3)).toBe('SELECT 1')
    expect(at(15)).toBe("SELECT 'a;b' -- c;")
    expect(at(text.length)).toBe('SELECT 3')
  })
  it('keeps the statement when the cursor sits right after its semicolon', () => {
    expect(at(9)).toBe('SELECT 1')
  })
  it('moves to the next statement from a blank line between two', () => {
    expect(at(10)).toBe("SELECT 'a;b' -- c;")
  })
  it('falls back to the last statement after trailing whitespace', () => {
    expect(statementRangeAt('SELECT 1;\n\n', 11)).toEqual({ start: 0, end: 8 })
    expect(statementRangeAt('   ', 1)).toBeNull()
  })
})

describe('runSummary', () => {
  it('counts the rows of a single statement', () => {
    expect(runSummary([{ ...base, data: [[1], [2]], elapsed_ms: 2 }])).toEqual({ ok: true, text: '2 rows · 2 ms' })
    expect(runSummary([{ ...base, data: [[1]] }])).toEqual({ ok: true, text: '1 row · 0 ms' })
  })
  it('says when the rows were capped', () => {
    expect(runSummary([{ ...base, data: Array(100).fill([1]), truncated: true, elapsed_ms: 5 }])).toEqual({
      ok: true,
      text: 'first 100 rows, more exist · 5 ms',
    })
  })
  it('shows the driver status for a statement without rows', () => {
    expect(runSummary([{ ...base, meta: null, status: 'INSERT 0 3', elapsed_ms: 3 }])).toEqual({
      ok: true,
      text: 'INSERT 0 3 · 3 ms',
    })
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
  it('names the failing statement and its error, nothing else', () => {
    const run = [
      { ...base, meta: null, status: 'OK', elapsed_ms: 3 },
      { ...base, ok: false, meta: null, message: 'no such table', sql: 'SELECT *\n  FROM nope' },
    ]
    expect(runSummary(run)).toEqual({ ok: false, text: 'Statement #2 Failed - no such table' })
  })
  it('handles an empty run', () => {
    expect(runSummary([])).toEqual({ ok: true, text: 'Nothing to run' })
  })
})

describe('failedSpan', () => {
  const script = 'SELECT 1;\nSELECT * FROM nope;\nSELECT 2'
  const failed = (n: number) => [
    ...Array.from({ length: n - 1 }, () => ({ ...base, meta: null, status: 'OK' })),
    { ...base, ok: false, meta: null, message: 'boom', sql: 'SELECT * FROM nope' },
  ]
  it('locates the failing statement of a whole-script run', () => {
    expect(failedSpan(script, 0, failed(2))).toEqual({ start: 10, end: 28 })
  })
  it('offsets into the script when only part of it ran', () => {
    const part = script.slice(10)
    expect(failedSpan(part, 10, failed(1))).toEqual({ start: 10, end: 28 })
  })
  it('is null when nothing failed', () => {
    expect(failedSpan(script, 0, [{ ...base, data: [[1]] }])).toBeNull()
    expect(failedSpan(script, 0, [])).toBeNull()
  })
})
