import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TAB_KEY, SESSION_KEY, tabRead, tabWrite } from './tabStorage'

function stubTabStorage(initial?: Record<string, string>) {
  const store = new Map<string, string>(Object.entries(initial ?? {}))
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  })
  return store
}

const SESSION = {
  id: 's1',
  label: 'Session 1',
  pinned: false,
  connection: null,
  database: null,
  workspace: 'default',
  url: '/queries',
  ui: {},
}

beforeEach(() => vi.resetModules())
afterEach(() => vi.unstubAllGlobals())

describe('tabStorage', () => {
  it('round-trips a value', () => {
    stubTabStorage()
    tabWrite(TAB_KEY, 'tab-1')
    expect(tabRead(TAB_KEY)).toBe('tab-1')
  })

  it('falls back to memory when sessionStorage throws', () => {
    const boom = () => {
      throw new Error('denied')
    }
    vi.stubGlobal('sessionStorage', { getItem: boom, setItem: boom, removeItem: boom })
    tabWrite(SESSION_KEY, 's-mem')
    // The tab still works for its lifetime; it just cannot survive a refresh.
    expect(tabRead(SESSION_KEY)).toBe('s-mem')
  })
})

describe('attachSession', () => {
  it('posts the tab token and remembers the returned id', async () => {
    const store = stubTabStorage()
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ ok: true, created: true, session: SESSION }) })
    vi.stubGlobal('fetch', fetchMock)
    const { attachSession } = await import('./session')

    const state = await attachSession()

    expect(state.id).toBe('s1')
    expect(store.get(SESSION_KEY)).toBe('s1')
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.tab).toBe(store.get(TAB_KEY))
  })

  it('sends the id it already has, so a refresh re-attaches', async () => {
    stubTabStorage({ [TAB_KEY]: 'tab-1', [SESSION_KEY]: 's-existing' })
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ ok: true, created: false, session: SESSION }) })
    vi.stubGlobal('fetch', fetchMock)
    const { attachSession } = await import('./session')

    await attachSession()

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.session_id).toBe('s-existing')
  })
})

describe('apiFetch', () => {
  it('sends the session id as a header', async () => {
    stubTabStorage({ [SESSION_KEY]: 's-header' })
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    const { apiFetch } = await import('./api')

    await apiFetch('/api/db/tables')

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>
    expect(headers['X-QV-Session']).toBe('s-header')
  })
})

describe('patchView', () => {
  it('coalesces rapid changes into one request', async () => {
    vi.useFakeTimers()
    stubTabStorage({ [TAB_KEY]: 'tab-1', [SESSION_KEY]: 's1' })
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ ok: true, session: SESSION }) })
    vi.stubGlobal('fetch', fetchMock)
    const { attachSession, patchView } = await import('./session')
    await attachSession()
    fetchMock.mockClear()

    patchView('query', { sql: 'S' })
    patchView('query', { sql: 'SE' })
    patchView('query', { sql: 'SEL' })
    await vi.advanceTimersByTimeAsync(500)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.ui.query.sql).toBe('SEL')
    vi.useRealTimers()
  })

  it('reads back locally before the write lands', async () => {
    vi.useFakeTimers()
    stubTabStorage({ [TAB_KEY]: 'tab-1', [SESSION_KEY]: 's1' })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, session: SESSION }) }),
    )
    const { attachSession, patchView, viewState } = await import('./session')
    await attachSession()

    patchView('explorer', { sidebarWidth: 412 })

    expect(viewState('explorer').sidebarWidth).toBe(412)
    vi.useRealTimers()
  })

  it('never rejects when the patch request fails', async () => {
    vi.useFakeTimers()
    stubTabStorage({ [TAB_KEY]: 'tab-1', [SESSION_KEY]: 's1' })
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ ok: true, session: SESSION }) })
    vi.stubGlobal('fetch', fetchMock)
    const { attachSession, patchView, flushPatches } = await import('./session')
    await attachSession()
    // The tab is attached; now the network goes away under a patch.
    fetchMock.mockRejectedValue(new Error('offline'))

    patchView('query', { sql: 'SELECT 1' })
    await vi.advanceTimersByTimeAsync(500)

    await expect(flushPatches()).resolves.toBeUndefined()
    vi.useRealTimers()
  })
})
