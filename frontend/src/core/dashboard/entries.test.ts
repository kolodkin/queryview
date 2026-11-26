import { expect, it } from 'vitest'
import {
  connectionNames,
  entryConnection,
  entrySql,
  federate,
  isFederated,
  unfederate,
  withConnection,
  withSql,
} from './entries'

const orders = { connection: 'warehouse', sql: 'SELECT 1', database: 'reporting' }
it('reads either shape', () => {
  expect(entrySql('SELECT 1')).toBe('SELECT 1')
  expect(entrySql(orders)).toBe('SELECT 1')
  expect(entryConnection('SELECT 1')).toBeNull()
  expect(entryConnection(orders)).toBe('warehouse')
})
it('editing the text keeps the connection and database', () => {
  expect(withSql(orders, 'SELECT 2')).toEqual({ ...orders, sql: 'SELECT 2' })
  expect(withSql('SELECT 1', 'SELECT 2')).toBe('SELECT 2')
})
it('picking a connection keeps the database only for the same one', () => {
  expect(withConnection(orders, 'warehouse')).toEqual(orders)
  expect(withConnection(orders, 'other')).toEqual({ connection: 'other', sql: 'SELECT 1' })
})
it('switches a whole dashboard between the two kinds', () => {
  const params = [
    { name: 'r', options_sql: 'SELECT r' },
    { name: 'k', options: ['a'] },
  ]
  const fed = federate({ a: 'SELECT 1', b: 'SELECT 2' }, params, 'analytics')
  expect(fed.queries).toEqual({
    a: { connection: 'analytics', sql: 'SELECT 1' },
    b: { connection: 'analytics', sql: 'SELECT 2' },
  })
  expect(fed.params).toEqual([{ ...params[0], connection: 'analytics' }, params[1]])
  expect(isFederated(fed.queries)).toBe(true)
  expect(unfederate({ ...fed.queries, b: orders }, fed.params)).toEqual({
    queries: { a: 'SELECT 1', b: 'SELECT 1' },
    params,
  })
})
it('lists the connections in first-use order', () => {
  expect(
    connectionNames({ a: orders, b: { connection: 'analytics', sql: 'x' }, c: orders }),
  ).toEqual(['warehouse', 'analytics'])
})
