import { describe, expect, it } from 'vitest'

import { CELL_WIDTH_CH, detectStructured, isOverflowing } from './structured'

describe('isOverflowing', () => {
  it('is false at or under the cell width', () => {
    expect(isOverflowing('')).toBe(false)
    expect(isOverflowing('x'.repeat(CELL_WIDTH_CH))).toBe(false)
  })

  it('is true past the cell width', () => {
    expect(isOverflowing('x'.repeat(CELL_WIDTH_CH + 1))).toBe(true)
  })
})

describe('detectStructured', () => {
  it('detects a JSON object', () => {
    const got = detectStructured('{"id": 1, "tags": ["a", "b"]}')
    expect(got).toEqual({ format: 'json', data: { id: 1, tags: ['a', 'b'] } })
  })

  it('detects a JSON array', () => {
    expect(detectStructured('[1, 2, 3]')).toEqual({ format: 'json', data: [1, 2, 3] })
  })

  it('rejects JSON scalars, which are not worth a popup', () => {
    expect(detectStructured('123')).toBeNull()
    expect(detectStructured('"quoted"')).toBeNull()
    expect(detectStructured('true')).toBeNull()
    expect(detectStructured('null')).toBeNull()
  })

  it('detects multi-line YAML mappings and sequences', () => {
    expect(detectStructured('id: 1\nname: alpha')).toEqual({
      format: 'yaml',
      data: { id: 1, name: 'alpha' },
    })
    expect(detectStructured('- one\n- two')).toEqual({ format: 'yaml', data: ['one', 'two'] })
  })

  // Almost any single-line string is valid YAML, so single-line text is left
  // alone unless it is real JSON.
  it('ignores single-line text that only YAML would claim', () => {
    expect(detectStructured('status: healthy')).toBeNull()
    expect(detectStructured('plain text value')).toBeNull()
    expect(detectStructured('C:\\path\\to\\file')).toBeNull()
  })

  it('ignores prose that happens to span lines', () => {
    expect(detectStructured('a long sentence\nand another one')).toBeNull()
  })

  it('returns null for empty, whitespace and unparseable text', () => {
    expect(detectStructured('')).toBeNull()
    expect(detectStructured('   ')).toBeNull()
    expect(detectStructured('{"unterminated": ')).toBeNull()
  })
})
