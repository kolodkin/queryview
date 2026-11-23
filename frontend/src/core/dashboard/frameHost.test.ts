import { afterEach, describe, expect, test, vi } from 'vitest'
import { answerWidget, listenToFrame, widgetPage, type WidgetPost } from './frameHost'
import type { WidgetRequest } from './widgetChannel'

const QUERY: WidgetRequest = {
  type: 'widget-query',
  id: 'w1',
  query: 'rows',
  limit: 50,
  offset: 100,
  orderBy: [{ name: 'amount', dir: 'DESC' }],
}
const DESCRIBE: WidgetRequest = { type: 'widget-describe', id: 'w2', query: 'rows' }
const CSV: WidgetRequest = { type: 'widget-csv', query: 'rows', limit: 50, offset: 0, orderBy: [] }

const never = () => {
  throw new Error('unexpected CSV error')
}
// A post that records what it was asked and answers with `reply`.
function fake(reply: Record<string, unknown>) {
  const calls: [string, WidgetRequest][] = []
  const post: WidgetPost = async (kind, req) => {
    calls.push([kind, req])
    return reply
  }
  return { calls, post }
}

describe('widgetPage', () => {
  test('is the paging a query or CSV request carries, in the API shape', () => {
    expect(widgetPage(QUERY)).toEqual({
      limit: 50,
      offset: 100,
      order_by: [{ name: 'amount', dir: 'DESC' }],
    })
    expect(widgetPage(CSV)).toEqual({ limit: 50, offset: 0, order_by: [], format: 'csv' })
    expect(widgetPage(DESCRIBE)).toEqual({})
  })
})

describe('answerWidget', () => {
  test('a describe reply becomes the widget fields', async () => {
    const { calls, post } = fake({ ok: true, fields: [{ name: 'amount', type: 'Int64' }] })
    expect(await answerWidget(DESCRIBE, post, never)).toEqual({
      type: 'widget-fields',
      id: 'w2',
      ok: true,
      fields: [{ name: 'amount', type: 'Int64' }],
    })
    expect(calls).toEqual([['describe', DESCRIBE]])
  })

  test('a query reply becomes the widget rows', async () => {
    const { calls, post } = fake({ ok: true, meta: [{ name: 'n', type: 'Int64' }], data: [[1]] })
    expect(await answerWidget(QUERY, post, never)).toEqual({
      type: 'widget-result',
      id: 'w1',
      ok: true,
      meta: [{ name: 'n', type: 'Int64' }],
      data: [[1]],
    })
    expect(calls).toEqual([['query', QUERY]])
  })

  test('a failure carries its message to the widget that asked', async () => {
    const { post } = fake({ ok: false, message: 'Waiting for a parameter choice.' })
    expect(await answerWidget(QUERY, post, never)).toEqual({
      type: 'widget-result',
      id: 'w1',
      ok: false,
      message: 'Waiting for a parameter choice.',
    })
    expect(await answerWidget(DESCRIBE, post, never)).toEqual({
      type: 'widget-fields',
      id: 'w2',
      ok: false,
      message: 'Waiting for a parameter choice.',
    })
  })

  test('a failure without a message still says something', async () => {
    const { post } = fake({ ok: false })
    expect(await answerWidget(QUERY, post, never)).toMatchObject({
      ok: false,
      message: 'query failed',
    })
  })

  test('a failed CSV has no reply to carry it: the host is told', async () => {
    const { post } = fake({ ok: false, message: 'too big' })
    const errors: string[] = []
    expect(await answerWidget(CSV, post, (m) => errors.push(m))).toBeNull()
    expect(errors).toEqual(['too big'])
  })

  test('a post that throws is a failed request, not an unanswered widget', async () => {
    const post: WidgetPost = async () => {
      throw new Error('offline')
    }
    expect(await answerWidget(QUERY, post, never)).toMatchObject({
      ok: false,
      message: 'request failed',
    })
  })
})

describe('listenToFrame', () => {
  afterEach(() => vi.unstubAllGlobals())

  // One frame, and the listener the host registered on `window`.
  function host(onSetParams: () => Promise<Record<string, unknown> | null>) {
    let listener: (e: unknown) => unknown = () => undefined
    vi.stubGlobal('window', {
      addEventListener: (_type: string, l: typeof listener) => (listener = l),
      removeEventListener: () => {},
    })
    const posted: unknown[] = []
    const contentWindow = { postMessage: (m: unknown) => posted.push(m) }
    const frame = { contentWindow } as unknown as HTMLIFrameElement
    listenToFrame(() => [frame], {
      onSnapshot: () => {},
      onWidget: async () => null,
      onSetParams,
    })
    const send = (data: unknown) => listener({ source: contentWindow, data })
    return { posted, send }
  }
  const ON = { type: 'qv-loading', on: true }
  const OFF = { type: 'qv-loading', on: false }

  test('a re-run is marked from its start until the last one queued has answered', async () => {
    const answers: ((a: Record<string, unknown>) => void)[] = []
    const { posted, send } = host(() => new Promise((r) => answers.push(r)))
    const first = send({ type: 'set-params', values: { pick: 'a' } })
    const second = send({ type: 'set-params', values: { pick: 'b' } })
    expect(posted).toEqual([ON, ON])
    answers[0]({ type: 'params-results', n: 1 })
    await first
    expect(posted.slice(2)).toEqual([{ type: 'params-results', n: 1 }])
    answers[1]({ type: 'params-results', n: 2 })
    await second
    expect(posted.slice(3)).toEqual([{ type: 'params-results', n: 2 }, OFF])
  })

  test('a request the host does not take marks nothing', async () => {
    const { posted, send } = host(async () => ({ type: 'params-results' }))
    await send({ type: 'set-params' })
    expect(posted).toEqual([])
  })

  test('a run that fails or is dropped still ends the mark', async () => {
    const dropped = host(async () => null)
    await dropped.send({ type: 'set-params', values: {} })
    expect(dropped.posted).toEqual([ON, OFF])
    const failed = host(() => Promise.reject(new Error('down')))
    await expect(failed.send({ type: 'set-params', values: {} })).rejects.toThrow('down')
    expect(failed.posted).toEqual([ON, OFF])
  })
})
