import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  RELEASES,
  RELEASES_SEEN_KEY,
  latestReleaseId,
  markAllSeen,
  readLastSeen,
  resetSeenCache,
  unreadCount,
} from './releases'
import { glossaryEntry } from './glossary'

// The unread rules are the whole reason this file is separable from React: the
// badge must be impossible to get STUCK, and impossible to make lie about a
// deployment. Both are pure functions of a date string, so both are tested here.

const TERM_MARK = /\[\[([^\]|]+)\|([^\]]+)\]\]/g

describe('the authored history', () => {
  it('is authored newest-first', () => {
    // Nothing sorts this at render time — deliberately, so a mis-ordered append
    // fails here loudly rather than being silently reordered on screen.
    for (let i = 1; i < RELEASES.length; i += 1) {
      expect(RELEASES[i - 1].date >= RELEASES[i].date).toBe(true)
    }
  })

  it('gives every entry a unique id, an ISO date and prose', () => {
    const ids = new Set(RELEASES.map((r) => r.id))
    expect(ids.size).toBe(RELEASES.length)
    for (const release of RELEASES) {
      expect(release.date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(release.title.length).toBeGreaterThan(0)
      expect(release.body.length).toBeGreaterThan(0)
    }
  })

  it('marks only terms the glossary actually defines', () => {
    // A mistyped key degrades to plain text with no underline — invisible on
    // screen, and the whole point of marking the word is lost.
    for (const release of RELEASES) {
      for (const match of release.body.matchAll(TERM_MARK)) {
        expect(glossaryEntry(match[1]), `${release.id}: [[${match[1]}]]`).toBeDefined()
      }
    }
  })

  it('marks TERMS, never whole clauses', () => {
    // A LAYOUT CONSTRAINT, not a style preference. <Explain>'s trigger is a
    // <button>, and Chrome blockifies a button to inline-block whatever the
    // stylesheet says (verified: `display: inline` computes to `inline-block`).
    // An inline-block is ATOMIC, so a label long enough to wrap becomes a
    // multi-line box sitting inside one line of prose — measured at 228x44 in a
    // 20px line — which forces that line open and tears the paragraph apart.
    // Four entries here marked 6-to-8-word clauses and the What Changed panel
    // rendered visibly broken, while every geometry assertion passed: no
    // overflow, nonzero size, correct stacking. Only a screenshot showed it.
    //
    // Reads RELEASES rather than the source file on purpose: this file's own
    // JSDoc contains a `[[key|the words to underline]]` example, and a
    // source-text scan would count documentation as data.
    for (const release of RELEASES) {
      for (const match of release.body.matchAll(TERM_MARK)) {
        const words = match[2].trim().split(/\s+/).length
        expect(words, `${release.id}: "${match[2]}" is ${words} words`).toBeLessThanOrEqual(3)
      }
    }
  })

  it('names at least one real scheduler job and leaves UI-only entries unbadged', () => {
    // Both halves matter: an entry that verifies nothing is honest only if
    // entries that CAN verify actually do.
    expect(RELEASES.some((r) => r.jobs && r.jobs.length > 0)).toBe(true)
    expect(RELEASES.some((r) => !r.jobs)).toBe(true)
    for (const release of RELEASES) {
      for (const job of release.jobs ?? []) expect(job).toMatch(/^[a-z_]+$/)
    }
  })
})

describe('unread', () => {
  beforeEach(() => {
    resetSeenCache()
    window.localStorage.clear()
  })
  afterEach(() => {
    resetSeenCache()
    window.localStorage.clear()
  })

  it('counts nothing unread when storage cannot be read', () => {
    // The failure this exists for: "all unread" on an unreadable store badges
    // forever, because nothing the reader does can ever clear it.
    expect(unreadCount(undefined)).toBe(0)
  })

  it('counts everything unread on a first run', () => {
    expect(unreadCount(null)).toBe(RELEASES.length)
  })

  it('counts only what shipped after the last-seen entry', () => {
    expect(unreadCount(latestReleaseId())).toBe(0)
    const oldest = RELEASES[RELEASES.length - 1].id
    expect(unreadCount(oldest)).toBe(RELEASES.length - 1)
  })

  it('badges a second entry shipped on the SAME DAY as the last one seen', () => {
    // THE REGRESSION THIS PINS. The seen token used to be the newest DATE and
    // the test was `release.date > seen`, so an entry appended the same day as
    // the one a reader had caught up to could never badge — `'2026-08-21' >
    // '2026-08-21'` is false. Not hypothetical: this list ships two or three
    // entries on a single date routinely, so the newest entry of most days was
    // invisible to anyone who had opened the panel earlier that day.
    // Newest-first, so RELEASES[i - 1] is the NEWER sibling of RELEASES[i].
    const olderIndex = RELEASES.findIndex(
      (release, index) => index > 0 && RELEASES[index - 1].date === release.date,
    )
    expect(olderIndex).toBeGreaterThan(0)
    const older = RELEASES[olderIndex]

    // Caught up to the older of a same-dated pair, the newer sibling is unread.
    expect(unreadCount(older.id)).toBe(olderIndex)

    // THE FENCE. This is what a date comparison would have answered, and it is
    // short by at least the same-dated sibling it cannot see. Reverting
    // unreadCount to `release.date > seen` makes these two equal and turns this
    // line red — which a plain `toBeGreaterThan(0)` would not have done.
    const whatDateComparisonWouldSay = RELEASES.filter((r) => r.date > older.date).length
    expect(unreadCount(older.id)).toBeGreaterThan(whatDateComparisonWouldSay)
  })

  it('treats an unrecognised seen id as caught up, never as everything-unread', () => {
    // A token from an older build, or an entry since renamed. Counting it as
    // all-unread would badge forever with nothing able to clear it — the same
    // failure the undefined case above exists to prevent.
    expect(unreadCount('no-such-release-id')).toBe(0)
  })

  it('reads undefined — not null — when localStorage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('site data blocked')
    })
    expect(readLastSeen()).toBeUndefined()
    expect(unreadCount(readLastSeen())).toBe(0)
  })

  it('persists the newest id on markAllSeen', () => {
    markAllSeen()
    expect(window.localStorage.getItem(RELEASES_SEEN_KEY)).toBe(latestReleaseId())
    expect(unreadCount(readLastSeen())).toBe(0)
  })

  it('still clears the badge when the WRITE throws', () => {
    // Storage can be readable and not writable — quota, or a browser that hands
    // back getItem and refuses setItem. Without the in-memory fallback the badge
    // would be uncleanable for the rest of the session.
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded')
    })
    expect(() => markAllSeen()).not.toThrow()
    expect(unreadCount(readLastSeen())).toBe(0)
  })
})
