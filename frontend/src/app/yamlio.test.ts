import { describe, expect, it } from 'vitest'
import { exportPath, filenameFromDisposition } from './yamlio'

describe('exportPath', () => {
  it('builds a dashboard export URL with all params', () => {
    expect(exportPath('dashboard', { name: 'top users', workspace: 'team' })).toBe(
      '/api/export?kind=dashboard&name=top+users&workspace=team',
    )
  })

  it('omits absent params for a workspace export', () => {
    expect(exportPath('workspace', { workspace: 'default' })).toBe(
      '/api/export?kind=workspace&workspace=default',
    )
  })
})

describe('filenameFromDisposition', () => {
  it('extracts the quoted filename', () => {
    expect(filenameFromDisposition('attachment; filename="my dash.dashboard.yaml"', 'x.yaml')).toBe(
      'my dash.dashboard.yaml',
    )
  })

  it('falls back when the header is missing or malformed', () => {
    expect(filenameFromDisposition(null, 'fallback.yaml')).toBe('fallback.yaml')
    expect(filenameFromDisposition('inline', 'fallback.yaml')).toBe('fallback.yaml')
  })
})
