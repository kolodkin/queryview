// DuckDB folder mode (docs/explorer.md): the connection's "databases" are the
// folders under its root as relative paths, "." being the root. The pill menu
// shows one level at a time; these helpers slice the flat list for it.

import type { Connection } from './connection'

// The menu's pseudo-entry that selects the parent folder.
export const PARENT = '..'

export function isFolderNav(c: Connection): boolean {
  return c.type === 'duckdb' && c.databases.length > 0
}

// The folder one level up, or null at the root.
export function parentFolder(path: string): string | null {
  if (path === '.') return null
  const i = path.lastIndexOf('/')
  return i < 0 ? '.' : path.slice(0, i)
}

// The direct children of `current`, in list order.
export function childFolders(databases: string[], current: string): string[] {
  return databases.filter((d) => parentFolder(d) === current)
}

// The folder's own name; the root shows its directory's name when known.
export function folderLabel(path: string, root?: string): string {
  const base = path === '.' && root ? root : path
  return base.slice(base.lastIndexOf('/') + 1) || base
}

export function fullPath(root: string, path: string): string {
  return path === '.' ? root : `${root}/${path}`
}
