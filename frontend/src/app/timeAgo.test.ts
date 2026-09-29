import { describe, expect, test } from 'vitest'
import { timeAgo } from './timeAgo'

const now = Date.UTC(2026, 0, 31, 12, 0, 0)
const ago = (sec: number) => timeAgo(now - sec * 1000, now)

describe('timeAgo', () => {
  test('under a minute is just now, and so is a clock skewed into the future', () => {
    expect(ago(0)).toBe('just now')
    expect(ago(59)).toBe('just now')
    expect(ago(-30)).toBe('just now')
  })

  test('minutes, hours and days', () => {
    expect(ago(60)).toBe('1 min ago')
    expect(ago(59 * 60)).toBe('59 min ago')
    expect(ago(3 * 3600)).toBe('3 h ago')
    expect(ago(2 * 86400)).toBe('2 d ago')
  })

  test('a month or older falls back to a date', () => {
    expect(ago(40 * 86400)).toBe(new Date(now - 40 * 86400 * 1000).toLocaleDateString())
  })
})
