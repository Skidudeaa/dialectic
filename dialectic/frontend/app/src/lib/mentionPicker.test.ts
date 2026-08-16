import { describe, expect, it } from 'vitest'
import { applyMention, matchCandidates, mentionQueryAt } from './mentionPicker'

const NAMES = ['Amo', 'Dan', 'Scott']

describe('mentionQueryAt', () => {
  it('opens on a bare @ at the start', () => {
    expect(mentionQueryAt('@', 1)).toEqual({ start: 0, end: 1, partial: '' })
  })

  it('opens on @ after a space', () => {
    expect(mentionQueryAt('hey @d', 6)).toEqual({ start: 4, end: 6, partial: 'd' })
  })

  it('opens after an opening paren', () => {
    expect(mentionQueryAt('(@d', 3)?.partial).toBe('d')
  })

  it('does NOT open inside an email', () => {
    expect(mentionQueryAt('amo@dialectic.example', 21)).toBeNull()
  })

  it('does NOT open mid-word', () => {
    expect(mentionQueryAt('foo@bar', 7)).toBeNull()
  })

  it('closes once the handle is followed by a space', () => {
    expect(mentionQueryAt('@dan ', 5)).toBeNull()
  })

  it('reads the token at the caret, not at the end of the line', () => {
    const text = '@dan and @sc later'
    //            0123456789          caret 12 sits just past "sc"
    expect(mentionQueryAt(text, 12)?.partial).toBe('sc')
    // ...and one character later the space has closed it again.
    expect(mentionQueryAt(text, 13)).toBeNull()
  })
})

describe('matchCandidates', () => {
  it('offers every human on a bare @', () => {
    expect(matchCandidates('', NAMES).map((c) => c.handle)).toEqual([
      'Amo', 'Dan', 'Scott', 'Dialectic',
    ])
  })

  it('filters by prefix, case-insensitively', () => {
    expect(matchCandidates('sc', NAMES).map((c) => c.label)).toEqual(['Scott'])
    expect(matchCandidates('SC', NAMES).map((c) => c.label)).toEqual(['Scott'])
  })

  it('offers a member who has never spoken', () => {
    // The whole reason /rooms/{id}/members exists: the roster used to be
    // online-users-plus-self, so a new member was unreachable until they
    // posted — which is the moment @-ing them matters least.
    expect(matchCandidates('s', ['Amo', 'Dan', 'Scott']).map((c) => c.label))
      .toContain('Scott')
  })

  it('puts the participant last', () => {
    const all = matchCandidates('', NAMES)
    expect(all[all.length - 1].kind).toBe('participant')
  })

  it('finds the participant by its own name', () => {
    expect(matchCandidates('dia', NAMES).map((c) => c.kind)).toEqual(['participant'])
  })

  it('returns nothing for a prefix nobody matches', () => {
    expect(matchCandidates('zzz', NAMES)).toEqual([])
  })
})

describe('applyMention', () => {
  const candidate = { handle: 'Scott', label: 'Scott', kind: 'human' as const }

  it('replaces the partial and leaves the caret past a trailing space', () => {
    const query = mentionQueryAt('hey @sc', 7)!
    expect(applyMention('hey @sc', query, candidate)).toEqual({
      text: 'hey @Scott ',
      caret: 11,
    })
  })

  it('preserves text after the caret', () => {
    const text = 'hey @sc what do you think?'
    const query = mentionQueryAt(text, 7)!
    expect(applyMention(text, query, candidate).text).toBe(
      'hey @Scott  what do you think?',
    )
  })

  it('the trailing space closes the picker it came from', () => {
    const query = mentionQueryAt('@sc', 3)!
    const next = applyMention('@sc', query, candidate)
    expect(mentionQueryAt(next.text, next.caret)).toBeNull()
  })
})

describe('the caret after a choice', () => {
  it('lands past the trailing space, so the picker cannot re-open', () => {
    // Regression fence: chooseMention used to re-derive the caret from the
    // textarea, which is STALE when we write the value ourselves — the
    // picker re-opened on the handle just finished and would have eaten the
    // next Enter. Browser acceptance caught it; this pins the arithmetic.
    const text = 'hey @Fix'
    const query = mentionQueryAt(text, text.length)!
    const next = applyMention(text, query, {
      handle: 'Fixture', label: 'Fixture Dan', kind: 'human',
    })
    expect(next.text).toBe('hey @Fixture ')
    expect(next.caret).toBe(next.text.length)
    expect(mentionQueryAt(next.text, next.caret)).toBeNull()
  })
})
