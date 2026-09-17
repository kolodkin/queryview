import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_SIDEBAR_WIDTH,
  MAX_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  clampSidebarWidth,
  loadSidebarWidth,
  saveSidebarWidth,
} from './explorerSettings'

// The width lives in the session's `ui` blob now, so the test fakes the session
// mirror rather than a storage backend.
const { ui } = vi.hoisted(() => ({ ui: { view: {} as Record<string, unknown> } }))
vi.mock('./session', () => ({
  viewState: () => ui.view,
  patchView: (_view: string, changes: Record<string, unknown>) => {
    ui.view = { ...ui.view, ...changes }
  },
}))

beforeEach(() => {
  ui.view = {}
})

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
  it('defaults with nothing remembered', () => {
    expect(loadSidebarWidth()).toBe(DEFAULT_SIDEBAR_WIDTH)
  })

  it('round-trips through the explorer view', () => {
    saveSidebarWidth(412)
    expect(loadSidebarWidth()).toBe(412)
  })

  it('clamps on the way in and on the way out', () => {
    saveSidebarWidth(MAX_SIDEBAR_WIDTH + 400)
    expect(loadSidebarWidth()).toBe(MAX_SIDEBAR_WIDTH)
    ui.view = { sidebarWidth: 10 }
    expect(loadSidebarWidth()).toBe(MIN_SIDEBAR_WIDTH)
  })

  it('defaults when the remembered width is not a number', () => {
    ui.view = { sidebarWidth: 'wide' }
    expect(loadSidebarWidth()).toBe(DEFAULT_SIDEBAR_WIDTH)
  })

  it('defaults when the view has other settings but no width', () => {
    ui.view = { future: 'keep me' }
    expect(loadSidebarWidth()).toBe(DEFAULT_SIDEBAR_WIDTH)
  })
})
