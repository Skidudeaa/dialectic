import { describe, expect, it } from 'vitest'
import { styleForKey, WORLD_STYLES, type WorldStyleKey } from './index.ts'

const ALL = WORLD_STYLES.map((s) => s.key) as WorldStyleKey[]

describe('styleForKey', () => {
  it('does not treat the Space bar as a digit', () => {
    // Number(' ') is 0, not NaN. Space is how a person scrolls the list under
    // the globe, so a guard that admits it silently resets their optics.
    expect(styleForKey(' ', ALL)).toBeNull()
  })

  it('rejects every other key that is not a single ASCII digit', () => {
    for (const key of ['h', 'H', 'Escape', 'Enter', 'Tab', 'ArrowUp', '',
                       '\t', '\n', '+1', '1.0', '01', '１', '-1', 'e5']) {
      expect(styleForKey(key, ALL), key).toBeNull()
    }
  })

  it('still selects a style for each digit shortcut the HUD advertises', () => {
    expect(styleForKey('0', ALL)).toBe('none')
    expect(styleForKey('1', ALL)).toBe('retro')
    expect(styleForKey('3', ALL)).toBe('thermal')
    expect(styleForKey('6', ALL)).toBe('anime')
    // Every advertised index resolves to the style shown beside that number.
    WORLD_STYLES.forEach((style, index) => {
      expect(styleForKey(String(index), ALL)).toBe(style.key)
    })
  })

  it('returns null for a digit past the end of the list', () => {
    expect(WORLD_STYLES.length).toBeLessThan(10)
    expect(styleForKey(String(WORLD_STYLES.length), ALL)).toBeNull()
    expect(styleForKey('9', ALL)).toBeNull()
  })

  it('refuses a style this GPU never compiled', () => {
    // worldStyleStages drops a stage the scene rejects; the keyboard must not
    // be a way around that.
    expect(styleForKey('3', ['none'])).toBeNull()
    expect(styleForKey('0', ['none'])).toBe('none')
  })
})
