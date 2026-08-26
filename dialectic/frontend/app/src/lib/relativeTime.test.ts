import { afterEach, describe, expect, it, vi } from 'vitest'
import { agoLabel } from './relativeTime'

describe('agoLabel', () => {
  afterEach(() => vi.useRealTimers())

  it('uses the same bounded human scale everywhere presence is rendered', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-25T18:00:00Z'))

    expect(agoLabel('2026-08-25T17:59:30Z')).toBe('just now')
    expect(agoLabel('2026-08-25T17:43:00Z')).toBe('17m ago')
    expect(agoLabel('2026-08-25T14:00:00Z')).toBe('4h ago')
    expect(agoLabel('2026-08-22T18:00:00Z')).toBe('3d ago')
    expect(agoLabel('2026-08-01T18:00:00Z')).toBe('a while ago')
  })

  it('does not fabricate an age for missing, invalid, or future clocks', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-25T18:00:00Z'))

    expect(agoLabel(null)).toBeNull()
    expect(agoLabel('not-a-clock')).toBeNull()
    expect(agoLabel('2026-08-25T18:01:00Z')).toBeNull()
  })
})
