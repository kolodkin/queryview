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
  it('coalesces queued changes into one backstop write', async () => {
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
    // Nothing goes out while the user is still in the panel...
    await vi.advanceTimersByTimeAsync(1_000)
    expect(fetchMock).not.toHaveBeenCalled()
    // ...and the backstop eventually sends one write, not three.
    await vi.advanceTimersByTimeAsync(5_000)

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
    await vi.advanceTimersByTimeAsync(6_000)

    await expect(flushPatches()).resolves.toBeUndefined()
    vi.useRealTimers()
  })
})

describe('activeWorkspace', () => {
  it('defaults to "default" before a session is attached', async () => {
    stubTabStorage()
    const { activeWorkspace } = await import('./session')
    expect(activeWorkspace()).toBe('default')
  })

  it("reports the attached session's workspace", async () => {
    stubTabStorage()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ok: true, session: { ...SESSION, workspace: 'team-a' } }),
      }),
    )
    const { attachSession, activeWorkspace } = await import('./session')

    await attachSession()

    expect(activeWorkspace()).toBe('team-a')
  })
})

describe('releaseSession', () => {
  it('beacons whatever the debounce has not flushed yet', async () => {
    // A reload fires pagehide inside the 400ms window, so an unflushed setting
    // (a dragged sidebar width) must still reach the server.
    vi.useFakeTimers()
    stubTabStorage({ [TAB_KEY]: 'tab-1', [SESSION_KEY]: 's1' })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, session: SESSION }) }),
    )
    const sent: string[] = []
    vi.stubGlobal('navigator', {
      sendBeacon: (_url: string, body: Blob) => {
        // Blob.text() is async; the payload is captured via the constructor arg
        // in the stub below instead.
        sent.push((body as unknown as { __text: string }).__text)
        return true
      },
    })
    vi.stubGlobal(
      'Blob',
      class {
        __text: string
        constructor(parts: string[]) {
          this.__text = parts.join('')
        }
      },
    )
    const { attachSession, patchView, releaseSession } = await import('./session')
    await attachSession()

    patchView('explorer', { sidebarWidth: 376 })
    releaseSession() // the page goes away before the debounce fires

    expect(sent).toHaveLength(1)
    const body = JSON.parse(sent[0])
    expect(body.tab).toBe('tab-1')
    expect(body.session_id).toBe('s1')
    expect(body.ui.explorer.sidebarWidth).toBe(376)
    vi.useRealTimers()
  })
})
