import { describe, expect, it } from 'vitest'

import { explorerUrl } from './connection'

describe('explorerUrl', () => {
  it('opens the last visited table when there is one', () => {
    expect(explorerUrl({ table: 'sales orders' })).toBe('/explorer?table=sales%20orders')
    expect(explorerUrl({})).toBe('/explorer')
  })
})
