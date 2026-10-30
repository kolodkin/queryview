import { describe, expect, it } from 'vitest'

import type { Connection } from './connection'
import { PARENT, childFolders, folderLabel, fullPath, isFolderNav, parentFolder } from './folderNav'

const conn = (over: Partial<Connection>): Connection => ({
  name: 'c',
  type: 'duckdb',
  databases: ['.', 'a'],
  database: '.',
  ...over,
})

describe('isFolderNav', () => {
  it('is a DuckDB connection with a folder list', () => {
    expect(isFolderNav(conn({}))).toBe(true)
    expect(isFolderNav(conn({ databases: [] }))).toBe(false)
    expect(isFolderNav(conn({ type: 'postgres' }))).toBe(false)
  })
})

describe('parentFolder', () => {
  it('walks one level up, and the root has no parent', () => {
    expect(parentFolder('.')).toBeNull()
    expect(parentFolder('a')).toBe('.')
    expect(parentFolder('a/b')).toBe('a')
  })
})

describe('childFolders', () => {
  it('lists the direct children of a folder in list order', () => {
    expect(childFolders(['.', 'a', 'a/b', 'c'], '.')).toEqual(['a', 'c'])
    expect(childFolders(['.', 'a', 'a/b'], 'a')).toEqual(['a/b'])
    expect(childFolders(['.', 'a', 'a/b'], 'a/b')).toEqual([])
  })
})

describe('folderLabel', () => {
  it('shows the last segment, and the root as its folder name', () => {
    expect(folderLabel('a/b')).toBe('b')
    expect(folderLabel('.', '/data/exports')).toBe('exports')
    expect(folderLabel('.')).toBe('.')
  })
})

describe('fullPath', () => {
  it('joins the root and the relative folder', () => {
    expect(fullPath('/data', '.')).toBe('/data')
    expect(fullPath('/data', 'a/b')).toBe('/data/a/b')
  })
})

it('names the parent pseudo-entry', () => {
  expect(PARENT).toBe('..')
})
