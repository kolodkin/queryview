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
  url: '/queryview',
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
    // Nothing goes out inside the idle window...
    await vi.advanceTimersByTimeAsync(1_000)
    expect(fetchMock).not.toHaveBeenCalled()
    // ...and one write, not three, once it lapses.
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
  it('is empty before a session is attached, so the backend picks its fallback', async () => {
    stubTabStorage()
    const { activeWorkspace } = await import('./session')
    expect(activeWorkspace()).toBe('')
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

describe('startHeartbeat', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    stubTabStorage()
    vi.stubGlobal('document', { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} })
    fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true, session: SESSION }) })
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.useRealTimers())

  it('reports a taken session and stops writing to it', async () => {
    const { attachSession, startHeartbeat, patchView, flushPatches, isTaken } = await import('./session')
    await attachSession()
    const onTaken = vi.fn()
    const stop = startHeartbeat({ onChanged: vi.fn(), onTaken })

    fetchMock.mockResolvedValue({ ok: false, status: 409, json: async () => ({ ok: false }) })
    await vi.advanceTimersByTimeAsync(10_000)

    expect(onTaken).toHaveBeenCalledOnce()
    expect(isTaken()).toBe(true)
    const beat = JSON.parse(fetchMock.mock.calls.at(-1)![1].body)
    expect(beat.keep).toBe(true)
    fetchMock.mockClear()
    patchView('query', { sql: 'SELECT 1' })
    await flushPatches()
    expect(fetchMock).not.toHaveBeenCalled()
    stop()
  })

  it('makes a session switch wait out a beat already in flight', async () => {
    const { attachSession, startHeartbeat, selectSession } = await import('./session')
    await attachSession()
    const stop = startHeartbeat({ onChanged: vi.fn(), onTaken: vi.fn() })
    let answerBeat!: () => void
    fetchMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          answerBeat = () => resolve({ ok: true, status: 200, json: async () => ({ ok: true, session: SESSION }) })
        }),
    )
    await vi.advanceTimersByTimeAsync(10_000)
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true, session: { ...SESSION, id: 's2' } }) })

    const switched = selectSession('s2')
    await vi.advanceTimersByTimeAsync(0)
    const urls = () => fetchMock.mock.calls.map((c) => String(c[0]))
    expect(urls().some((u) => u.includes('/select'))).toBe(false)

    answerBeat()
    expect((await switched)?.id).toBe('s2')
    expect(urls().at(-1)).toContain('/api/sessions/select')
    stop()
  })

  it('makes a database switch wait out a beat in flight and holds the next one', async () => {
    const { attachSession, startHeartbeat, onSessionRow } = await import('./session')
    const { selectDatabase } = await import('./connection')
    await attachSession()
    const stop = startHeartbeat({ onChanged: vi.fn(), onTaken: vi.fn() })
    const onRow = vi.fn()
    onSessionRow(onRow)
    // A beat that read the row before the switch: it must land before the
    // switch starts, never after it, or the shell would follow its stale database.
    let answerBeat!: () => void
    fetchMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          answerBeat = () =>
            resolve({ ok: true, status: 200, json: async () => ({ ok: true, session: { ...SESSION, database: 'old' } }) })
        }),
    )
    await vi.advanceTimersByTimeAsync(10_000)
    let answerSwitch!: () => void
    fetchMock.mockImplementation((url: string) =>
      String(url).includes('/api/db/database')
        ? new Promise((resolve) => {
            answerSwitch = () => resolve({ ok: true, status: 200, json: async () => ({ ok: true }) })
          })
        : Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true, session: SESSION }) }),
    )

    const switched = selectDatabase('new')
    await vi.advanceTimersByTimeAsync(0)
    const urls = () => fetchMock.mock.calls.map((c) => String(c[0]))
    expect(urls().some((u) => u.includes('/api/db/database'))).toBe(false)

    answerBeat()
    await vi.advanceTimersByTimeAsync(0)
    expect(onRow).toHaveBeenCalledWith(expect.objectContaining({ database: 'old' }))
    expect(urls().at(-1)).toContain('/api/db/database')
    // No beat starts while the switch is in flight, however long it takes.
    await vi.advanceTimersByTimeAsync(30_000)
    expect(urls().filter((u) => u.includes('/attach'))).toHaveLength(2)

    answerSwitch()
    expect(await switched).toBe(true)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(urls().filter((u) => u.includes('/attach'))).toHaveLength(3)
    stop()
  })

  it('hands a different session to onChanged', async () => {
    const { attachSession, startHeartbeat } = await import('./session')
    await attachSession()
    const onChanged = vi.fn()
    const stop = startHeartbeat({ onChanged, onTaken: vi.fn() })

    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true, session: { ...SESSION, id: 's2' } }) })
    await vi.advanceTimersByTimeAsync(10_000)

    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ id: 's2' }))
    stop()
  })

  it('hands every adopted row to onSessionRow, whatever brought it', async () => {
    const { attachSession, startHeartbeat, onSessionRow, patchView, flushPatches } = await import('./session')
    await attachSession()
    const onRow = vi.fn()
    const stopRows = onSessionRow(onRow)
    const stop = startHeartbeat({ onChanged: vi.fn(), onTaken: vi.fn() })

    // A beat: the same session, switched to another database elsewhere.
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, session: { ...SESSION, connection: 'c1', database: 'sales' } }),
    })
    await vi.advanceTimersByTimeAsync(10_000)
    expect(onRow).toHaveBeenCalledOnce()
    expect(onRow).toHaveBeenCalledWith(expect.objectContaining({ connection: 'c1', database: 'sales' }))

    // A queued write's response carries the row too.
    patchView('query', { sql: 'SELECT 1' })
    await flushPatches()
    expect(onRow).toHaveBeenCalledTimes(2)

    stopRows()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(onRow).toHaveBeenCalledTimes(2)
    stop()
  })
})
