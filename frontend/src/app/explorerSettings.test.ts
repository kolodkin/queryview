import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_SIDEBAR_WIDTH,
  MAX_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  clampSidebarWidth,
  loadSidebarWidth,
  saveSidebarWidth,
} from './explorerSettings'
import { stubStorage } from './testStorage'

afterEach(() => vi.unstubAllGlobals())

describe('clampSidebarWidth', () => {
  it('keeps a width inside the drag range', () => {
    expect(clampSidebarWidth(320)).toBe(320)
    expect(clampSidebarWidth(MIN_SIDEBAR_WIDTH - 50)).toBe(MIN_SIDEBAR_WIDTH)
    expect(clampSidebarWidth(MAX_SIDEBAR_WIDTH + 50)).toBe(MAX_SIDEBAR_WIDTH)
  })

  it('rounds to whole pixels', () => {
    expect(clampSidebarWidth(320.6)).toBe(321)
  })

  it('falls back to the default for a non-finite width', () => {
    expect(clampSidebarWidth(Number.NaN)).toBe(DEFAULT_SIDEBAR_WIDTH)
    expect(clampSidebarWidth(Number.POSITIVE_INFINITY)).toBe(DEFAULT_SIDEBAR_WIDTH)
  })
})

describe('the remembered sidebar width', () => {
  it('defaults with nothing stored', () => {
    stubStorage()
    expect(loadSidebarWidth()).toBe(DEFAULT_SIDEBAR_WIDTH)
  })

  it('round-trips through the explorer view key', () => {
    const store = stubStorage()
    saveSidebarWidth(412)
    expect(store.get('qv_view_explorer')).toBe('{"sidebarWidth":412}')
    expect(loadSidebarWidth()).toBe(412)
  })

  it('clamps on the way in and on the way out', () => {
    stubStorage()
    saveSidebarWidth(MAX_SIDEBAR_WIDTH + 400)
    expect(loadSidebarWidth()).toBe(MAX_SIDEBAR_WIDTH)
    stubStorage({ 'qv_view_explorer': '{"sidebarWidth":10}' })
    expect(loadSidebarWidth()).toBe(MIN_SIDEBAR_WIDTH)
  })

  it('defaults when the stored width is not a number', () => {
    stubStorage({ 'qv_view_explorer': '{"sidebarWidth":"wide"}' })
    expect(loadSidebarWidth()).toBe(DEFAULT_SIDEBAR_WIDTH)
  })

  it('defaults when the view has other settings but no width', () => {
    stubStorage({ 'qv_view_explorer': '{"future":"keep me"}' })
    expect(loadSidebarWidth()).toBe(DEFAULT_SIDEBAR_WIDTH)
  })
})
