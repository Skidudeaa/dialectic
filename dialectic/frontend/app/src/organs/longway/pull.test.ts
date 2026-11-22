import { describe, expect, it } from 'vitest'
import { cleanPull } from './pull'

describe('cleanPull', () => {
  it('removes bare citation ids and tidies spaces and punctuation', () => {
    expect(cleanPull('covers Old Nubia S123, a dahabiya')).toBe('covers Old Nubia, a dahabiya')
    expect(cleanPull('window S8 S9.')).toBe('window.')
    expect(cleanPull('advised against or at war S53 S83 S93.')).toBe('advised against or at war.')
    expect(cleanPull('dates from 1938 S2 (unverified).')).toBe('dates from 1938 (unverified).')
    expect(
      cleanPull(
        'a ship across the lake that covers Old Nubia S123, a dahabiya under sail between Aswan and Esna that ties up to islands at night S177 S173, the sleeper north S200, and a walk to the point at Ras el-Bar where the river meets the Mediterranean S229.',
      ),
    ).toBe(
      'a ship across the lake that covers Old Nubia, a dahabiya under sail between Aswan and Esna that ties up to islands at night, the sleeper north, and a walk to the point at Ras el-Bar where the river meets the Mediterranean.',
    )
  })

  it('removes markdown citation links while keeping ordinary markdown links intact', () => {
    expect(
      cleanPull(
        'covers Old Nubia [S123](https://kasribrim.com/), ties up at night [S177](https://a.example) [S173](https://b.example), and visits [Philae](https://philae.example).',
      ),
    ).toBe('covers Old Nubia, ties up at night, and visits [Philae](https://philae.example).')
    expect(cleanPull('falls inside the 2027 window [S8] [S9].')).toBe('falls inside the 2027 window.')
  })

  it('leaves ordinary words and ship or road names untouched', () => {
    expect(cleanPull('Sail aboard the SS Sudan around the S-curve.')).toBe('Sail aboard the SS Sudan around the S-curve.')
    expect(cleanPull('Take US1 past S12a and S-12.')).toBe('Take US1 past S12a and S-12.')
    expect(cleanPull('')).toBe('')
  })
})
