import { describe, expect, it } from 'vitest'
import {
  anchorField,
  anchorFromSelection,
  hashQuote,
  locateAnchor,
  normaliseQuote,
} from './passageAnchor'

const MESSAGE =
  'tanker rates moved before crude did, twice this month. that is a ' +
  'correlation, not a mechanism. but tanker rates moved before crude did again.'

describe('normaliseQuote', () => {
  it('collapses whitespace so a re-wrap does not break the anchor', () => {
    expect(normaliseQuote('  tanker   rates\n  moved ')).toBe('tanker rates moved')
  })
})

describe('locateAnchor', () => {
  it('finds a unique passage', () => {
    const at = locateAnchor(MESSAGE, { quote: 'not a mechanism', occurrence: 0 })
    expect(at).not.toBeNull()
    expect(MESSAGE.slice(at!.start, at!.end)).toBe('not a mechanism')
  })

  it('distinguishes the SECOND occurrence from the first', () => {
    const quote = 'tanker rates moved before crude did'
    const first = locateAnchor(MESSAGE, { quote, occurrence: 0 })!
    const second = locateAnchor(MESSAGE, { quote, occurrence: 1 })!
    expect(second.start).toBeGreaterThan(first.start)
    expect(MESSAGE.slice(second.start, second.end)).toBe(quote)
  })

  it('survives an edit elsewhere in the message', () => {
    const edited = MESSAGE.replace('twice this month', 'three times this month')
    const at = locateAnchor(edited, { quote: 'not a mechanism', occurrence: 0 })
    expect(at).not.toBeNull()
    expect(edited.slice(at!.start, at!.end)).toBe('not a mechanism')
  })

  it('returns null when the quote is gone, rather than guessing', () => {
    // The honest degrade. Painting a range that no longer matches would put
    // a mark on a sentence nobody wrote.
    const edited = MESSAGE.replace('not a mechanism', 'plausibly causal')
    expect(locateAnchor(edited, { quote: 'not a mechanism', occurrence: 0 })).toBeNull()
  })

  it('falls back to the first occurrence when a repetition was deleted', () => {
    const quote = 'tanker rates moved before crude did'
    const edited = MESSAGE.replace(
      ' but tanker rates moved before crude did again.', '',
    )
    const at = locateAnchor(edited, { quote, occurrence: 1 })
    expect(at).not.toBeNull()
    expect(edited.slice(at!.start, at!.end)).toBe(quote)
  })

  it('matches across a whitespace re-wrap', () => {
    const rewrapped = MESSAGE.replace('not a mechanism', 'not  a\nmechanism')
    expect(locateAnchor(rewrapped, { quote: 'not a mechanism', occurrence: 0 })).not.toBeNull()
  })
})

describe('anchorField', () => {
  it('is stable for the same quote and occurrence', () => {
    const a = { quote: 'not a mechanism', occurrence: 0 }
    expect(anchorField(a)).toBe(anchorField({ ...a }))
  })

  it('DIFFERS for two passages of one message', () => {
    // The property that makes a highlighter possible: field_marks folds
    // `field` into the dedup key, so same-message highlights must not
    // produce the same field or the second one silently no-ops.
    const a = anchorField({ quote: 'not a mechanism', occurrence: 0 })
    const b = anchorField({ quote: 'twice this month', occurrence: 0 })
    expect(a).not.toBe(b)
  })

  it('DIFFERS for two occurrences of the same quote', () => {
    const quote = 'tanker rates moved before crude did'
    expect(anchorField({ quote, occurrence: 0 }))
      .not.toBe(anchorField({ quote, occurrence: 1 }))
  })

  it('is short enough to live in a dedup key', () => {
    expect(anchorField({ quote: 'x'.repeat(300), occurrence: 9 }).length).toBeLessThan(32)
  })
})

describe('hashQuote', () => {
  it('is deterministic', () => {
    expect(hashQuote('tanker rates')).toBe(hashQuote('tanker rates'))
  })

  it('separates near-identical quotes', () => {
    expect(hashQuote('not a mechanism')).not.toBe(hashQuote('not a mechanisn'))
  })
})

describe('anchorFromSelection', () => {
  function selectWithin(html: string, text: string) {
    const container = document.createElement('div')
    container.innerHTML = html
    document.body.appendChild(container)
    const node = container.firstChild!.firstChild as Text
    const start = node.data.indexOf(text)
    const range = document.createRange()
    range.setStart(node, start)
    range.setEnd(node, start + text.length)
    const selection = window.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)
    return { container, selection }
  }

  it('builds an anchor from a real selection', () => {
    const { container, selection } = selectWithin(
      `<p>${MESSAGE}</p>`, 'not a mechanism',
    )
    const anchor = anchorFromSelection(selection, container)
    expect(anchor).toEqual({ quote: 'not a mechanism', occurrence: 0 })
    container.remove()
  })

  it('counts the occurrence from the text BEFORE the selection', () => {
    const quote = 'tanker rates moved before crude did'
    const { container, selection } = selectWithin(`<p>${MESSAGE}</p>`, quote)
    // selectWithin picks the FIRST match, so occurrence 0.
    expect(anchorFromSelection(selection, container)?.occurrence).toBe(0)
    container.remove()
  })

  it('refuses a collapsed selection', () => {
    const container = document.createElement('div')
    expect(anchorFromSelection(window.getSelection(), container)).toBeNull()
  })

  it('refuses a selection that is too short to mean anything', () => {
    const { container, selection } = selectWithin('<p>ab cd</p>', 'ab')
    expect(anchorFromSelection(selection, container)).toBeNull()
    container.remove()
  })

  it('refuses a selection outside the message', () => {
    const { container, selection } = selectWithin(`<p>${MESSAGE}</p>`, 'not a mechanism')
    const elsewhere = document.createElement('div')
    document.body.appendChild(elsewhere)
    expect(anchorFromSelection(selection, elsewhere)).toBeNull()
    container.remove()
    elsewhere.remove()
  })
})
