import { expect, test } from 'vitest'
import { filterDatabases } from './databaseFilter'

const dbs = ['INFORMATION_SCHEMA', 'sales_reporting', 'sales_2026_09_08', 'default', 'system']

test('empty or blank query keeps every database in order', () => {
  expect(filterDatabases(dbs, '')).toEqual(dbs)
  expect(filterDatabases(dbs, '   ')).toEqual(dbs)
})

test('matches a case-insensitive substring anywhere in the name', () => {
  expect(filterDatabases(dbs, 'reporting')).toEqual(['sales_reporting'])
  expect(filterDatabases(dbs, 'SCHEMA')).toEqual(['INFORMATION_SCHEMA'])
  expect(filterDatabases(dbs, 'information')).toEqual(['INFORMATION_SCHEMA'])
})

test('trims the query and keeps original order for several matches', () => {
  expect(filterDatabases(dbs, ' a ')).toEqual([
    'INFORMATION_SCHEMA',
    'sales_reporting',
    'sales_2026_09_08',
    'default',
  ])
})

test('no match yields an empty list', () => {
  expect(filterDatabases(dbs, 'zzz')).toEqual([])
})
