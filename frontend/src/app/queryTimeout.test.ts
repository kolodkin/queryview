import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_QUERY_TIMEOUT,
  MAX_QUERY_TIMEOUT,
  loadQueryTimeout,
  parseQueryTimeout,
  saveQueryTimeout,
} from './queryTimeout'

// The value lives in the session's `ui` blob, so the test fakes the session
// mirror and counts the flushes the backend depends on.
const { ui } = vi.hoisted(() => ({
  ui: { view: {} as Record<string, unknown>, flushes: 0 },
}))
vi.mock('./session', () => ({
  viewState: () => ui.view,
  patchView: (_view: string, changes: Record<string, unknown>) => {
    ui.view = { ...ui.view, ...changes }
  },
  flushPatches: async () => {
    ui.flushes++
  },
}))

beforeEach(() => {
  ui.view = {}
  ui.flushes = 0
})

describe('the query timeout', () => {
  it('defaults with nothing remembered, or a value that is not a number', () => {
    expect(loadQueryTimeout()).toBe(DEFAULT_QUERY_TIMEOUT)
    ui.view = { queryTimeout: 'slow' }
    expect(loadQueryTimeout()).toBe(DEFAULT_QUERY_TIMEOUT)
  })

  it('saves whole seconds within 1..MAX and flushes them to the session', async () => {
    expect(await saveQueryTimeout(45)).toBe(45)
    expect(loadQueryTimeout()).toBe(45)
    expect(ui.flushes).toBe(1)
    expect(await saveQueryTimeout(0)).toBe(1)
    expect(await saveQueryTimeout(MAX_QUERY_TIMEOUT + 1)).toBe(MAX_QUERY_TIMEOUT)
    expect(await saveQueryTimeout(2.6)).toBe(3)
    expect(await saveQueryTimeout(Number.NaN)).toBe(DEFAULT_QUERY_TIMEOUT)
  })
})

describe('parseQueryTimeout', () => {
  it('reads a typed number and rejects a blank or non-number', () => {
    expect(parseQueryTimeout('10')).toBe(10)
    expect(parseQueryTimeout(' 25 ')).toBe(25)
    expect(parseQueryTimeout('')).toBeNull()
    expect(parseQueryTimeout('abc')).toBeNull()
  })
})
