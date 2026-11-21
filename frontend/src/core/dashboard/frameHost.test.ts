import { describe, expect, test } from 'vitest'
import { answerWidget, widgetPage, type WidgetPost } from './frameHost'
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
