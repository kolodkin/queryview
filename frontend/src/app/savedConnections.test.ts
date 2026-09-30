import { describe, expect, test } from 'vitest'
import { driverCounts, matchConnections, type SavedConnection } from './savedConnections'

const conn = (name: string, type: string, database: string | null = null): SavedConnection => ({
  name,
  type,
  database,
  last_active_at: 0,
})

const list = [
  conn('reporting', 'clickhouse', 'sales_reporting'),
  conn('warehouse', 'postgres', 'inventory'),
  conn('scratch', 'duckdb'),
  conn('analytics', 'clickhouse', 'events'),
]
const labels: Record<string, string> = { clickhouse: 'ClickHouse', postgres: 'Postgres', duckdb: 'DuckDB' }
const names = (q: string, type: string | null = null) =>
  matchConnections(list, q, type, (t) => labels[t] ?? t).map((c) => c.name)

describe('matchConnections', () => {
  test('an empty query keeps everything, in order', () => {
    expect(names('')).toEqual(['reporting', 'warehouse', 'scratch', 'analytics'])
  })

  test('matches name, type, label and database, case-insensitively', () => {
    expect(names('WARE')).toEqual(['warehouse'])
    expect(names('postgres')).toEqual(['warehouse'])
    expect(names('duck')).toEqual(['scratch'])
    expect(names('sales')).toEqual(['reporting'])
  })

  test('every term must match', () => {
    expect(names('clickhouse events')).toEqual(['analytics'])
    expect(names('clickhouse inventory')).toEqual([])
  })

  test('a driver narrows the list', () => {
    expect(names('', 'clickhouse')).toEqual(['reporting', 'analytics'])
    expect(names('sales', 'postgres')).toEqual([])
  })
})

describe('driverCounts', () => {
  test('counts per driver, most common first', () => {
    expect(driverCounts(list)).toEqual([
      ['clickhouse', 2],
      ['duckdb', 1],
      ['postgres', 1],
    ])
  })
})
