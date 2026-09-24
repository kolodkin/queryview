import { expect, test } from 'vitest'
import { filterNames } from './nameFilter'

const dbs = ['INFORMATION_SCHEMA', 'sales_reporting', 'sales_2026_09_08', 'default', 'system']

test('empty or blank query keeps every database in order', () => {
  expect(filterNames(dbs, '')).toEqual(dbs)
  expect(filterNames(dbs, '   ')).toEqual(dbs)
})

test('matches a case-insensitive substring anywhere in the name', () => {
  expect(filterNames(dbs, 'reporting')).toEqual(['sales_reporting'])
  expect(filterNames(dbs, 'SCHEMA')).toEqual(['INFORMATION_SCHEMA'])
  expect(filterNames(dbs, 'information')).toEqual(['INFORMATION_SCHEMA'])
})

test('trims the query and keeps original order for several matches', () => {
  expect(filterNames(dbs, ' a ')).toEqual([
    'INFORMATION_SCHEMA',
    'sales_reporting',
    'sales_2026_09_08',
    'default',
  ])
})

test('no match yields an empty list', () => {
  expect(filterNames(dbs, 'zzz')).toEqual([])
})

test('matches objects by the name the accessor picks', () => {
  const fields = [{ name: 'asset_id' }, { name: 'host_name' }]
  expect(filterNames(fields, 'HOST', (f) => f.name)).toEqual([{ name: 'host_name' }])
})
