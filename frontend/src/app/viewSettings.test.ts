import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadViewSettings, patchViewSettings } from './viewSettings'

// Mirrors workspace.test.ts: the node test environment has no localStorage.
function stubStorage(initial?: Record<string, string>) {
  const store = new Map<string, string>(Object.entries(initial ?? {}))
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
  })
  return store
}

afterEach(() => vi.unstubAllGlobals())

describe('loadViewSettings', () => {
  it('is empty with nothing stored', () => {
    stubStorage()
    expect(loadViewSettings('explorer')).toEqual({})
  })

  it('reads the view key as JSON', () => {
    stubStorage({ 'qv_view_explorer': '{"sidebarWidth":412}' })
    expect(loadViewSettings('explorer')).toEqual({ sidebarWidth: 412 })
  })

  it('keeps views in separate keys', () => {
    stubStorage({
      'qv_view_explorer': '{"sidebarWidth":412}',
      'qv_view_dashboard': '{"sidebarWidth":300}',
    })
    expect(loadViewSettings('explorer')).toEqual({ sidebarWidth: 412 })
    expect(loadViewSettings('dashboard')).toEqual({ sidebarWidth: 300 })
  })

  it('is empty when the stored value is not a JSON object', () => {
    stubStorage({ 'qv_view_explorer': 'not json' })
    expect(loadViewSettings('explorer')).toEqual({})
    stubStorage({ 'qv_view_explorer': '[1,2]' })
    expect(loadViewSettings('explorer')).toEqual({})
    stubStorage({ 'qv_view_explorer': 'null' })
    expect(loadViewSettings('explorer')).toEqual({})
  })

  it('is empty when storage throws', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('denied')
      },
    })
    expect(loadViewSettings('explorer')).toEqual({})
  })
})

describe('patchViewSettings', () => {
  it('round-trips a setting', () => {
    stubStorage()
    patchViewSettings('explorer', { sidebarWidth: 412 })
    expect(loadViewSettings('explorer')).toEqual({ sidebarWidth: 412 })
  })

  it('merges into the view, leaving other settings intact', () => {
    stubStorage({ 'qv_view_explorer': '{"sidebarWidth":412,"future":"keep me"}' })
    patchViewSettings('explorer', { sidebarWidth: 300 })
    expect(loadViewSettings('explorer')).toEqual({ sidebarWidth: 300, future: 'keep me' })
  })

  it('does not touch another view', () => {
    const store = stubStorage({ 'qv_view_dashboard': '{"sidebarWidth":300}' })
    patchViewSettings('explorer', { sidebarWidth: 412 })
    expect(store.get('qv_view_dashboard')).toBe('{"sidebarWidth":300}')
  })

  it('does not throw when storage throws', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => null,
      setItem: () => {
        throw new Error('denied')
      },
    })
    expect(() => patchViewSettings('explorer', { sidebarWidth: 412 })).not.toThrow()
  })
})
