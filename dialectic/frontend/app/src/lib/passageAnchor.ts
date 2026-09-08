import type { MessageRef } from '../types'

/**
 * Anchoring a highlight to a passage of a message.
 *
 * THE PROBLEM, stated plainly: messages are editable (MessageBubble's
 * onEdit), and the transcript renders markdown through marked, so a
 * character offset into the SOURCE does not address anything in the rendered
 * DOM, and either one moves the moment somebody fixes a typo. An anchor built
 * on offsets alone silently highlights the wrong words later — which is worse
 * than losing the highlight, because it puts a mark on a sentence nobody
 * wrote.
 *
 * SO: the quote text is the anchor, and the offset is only a hint used to
 * disambiguate repeats. If the quote is no longer present the highlight
 * degrades VISIBLY to "quoted from an edited message" rather than guessing.
 *
 * Same instinct as `quoteExcerpt` in MessageBubble, which has flattened
 * markdown for reply quotes since before this existed.
 */

/** Long enough to be unambiguous, short enough to survive light editing. */
export const MAX_QUOTE_CHARS = 300
export const MIN_QUOTE_CHARS = 3

export interface PassageAnchor {
  /** The exact text selected, normalised for whitespace. */
  quote: string
  /** Which occurrence of `quote` this was — 0-based. */
  occurrence: number
}

/** Collapse runs of whitespace so a re-wrap does not break the anchor. */
export function normaliseQuote(raw: string): string {
  return raw.replace(/\s+/g, ' ').trim()
}

/**
 * The subject `field` for a passage anchor.
 *
 * WHY it goes in `field` and not the payload: `field_marks._subject_token`
 * folds `field` into the dedup key (`entity:id#field`), so two highlights on
 * different passages of ONE message get different keys and can coexist.
 * Anchoring in the payload instead would make every highlight on a message
 * collide with the first.
 */
export function anchorField(anchor: PassageAnchor): string {
  return `quote:${anchor.occurrence}:${hashQuote(anchor.quote)}`
}

/**
 * A short, stable, non-cryptographic digest. Only needs to distinguish
 * passages within one message — collisions across messages are irrelevant
 * because the subject id already separates them.
 */
export function hashQuote(quote: string): string {
  let h = 2166136261
  for (let i = 0; i < quote.length; i++) {
    h ^= quote.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return (h >>> 0).toString(36)
}

/**
 * Build an anchor from a live DOM selection inside one message element.
 *
 * Returns null when the selection is empty, collapsed, too short to be
 * meaningful, or escapes the message — a highlight spanning two people's
 * words is not a passage of either.
 */
export function anchorFromSelection(
  selection: Selection | null,
  container: HTMLElement,
): PassageAnchor | null {
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null
  const range = selection.getRangeAt(0)
  if (!container.contains(range.commonAncestorContainer)) return null

  const quote = normaliseQuote(selection.toString())
  if (quote.length < MIN_QUOTE_CHARS) return null
  if (quote.length > MAX_QUOTE_CHARS) return null

  // Which occurrence: count identical earlier matches in the text BEFORE the
  // selection starts, so highlighting the second "no" in a message does not
  // resolve to the first.
  const before = document.createRange()
  before.setStart(container, 0)
  before.setEnd(range.startContainer, range.startOffset)
  const occurrence = countOccurrences(normaliseQuote(before.toString()), quote)

  return { quote, occurrence }
}

function countOccurrences(haystack: string, needle: string): number {
  if (!needle) return 0
  let count = 0
  let index = haystack.indexOf(needle)
  while (index !== -1) {
    count += 1
    index = haystack.indexOf(needle, index + needle.length)
  }
  return count
}

/**
 * Where the anchor lands in the CURRENT text, or null when it no longer
 * does. Null is the honest answer after an edit — the caller shows the quote
 * as text rather than painting a range that may no longer mean what it did.
 */
export function locateAnchor(
  content: string,
  anchor: PassageAnchor,
): { start: number; end: number } | null {
  const haystack = normaliseQuote(content)
  let index = haystack.indexOf(anchor.quote)
  let seen = 0
  while (index !== -1) {
    if (seen === anchor.occurrence) {
      return { start: index, end: index + anchor.quote.length }
    }
    seen += 1
    index = haystack.indexOf(anchor.quote, index + anchor.quote.length)
  }
  // The requested occurrence is gone. Fall back to the FIRST occurrence if
  // the quote still exists at all — an edit that deleted one repetition
  // should not orphan a mark on a sentence that is still there.
  const first = haystack.indexOf(anchor.quote)
  if (first !== -1) return { start: first, end: first + anchor.quote.length }
  return null
}

/** Find an unambiguous quote in rendered text, preserving offsets through inline markup. */
export function uniqueQuoteRange(container: HTMLElement, quote: string): Range | null {
  const needle = normaliseQuote(quote)
  if (!needle) return null
  const positions: { node: Text; offset: number }[] = []
  let text = ''
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  let node: Node | null
  while ((node = walker.nextNode())) {
    const value = node.textContent ?? ''
    for (let offset = 0; offset < value.length; offset++) {
      const char = /\s/.test(value[offset]) ? ' ' : value[offset]
      if (char === ' ' && (!text || text.endsWith(' '))) continue
      text += char
      positions.push({ node: node as Text, offset })
    }
  }
  const start = text.indexOf(needle)
  if (start < 0 || text.indexOf(needle, start + 1) >= 0) return null
  const first = positions[start]
  const last = positions[start + needle.length - 1]
  const range = document.createRange()
  range.setStart(first.node, first.offset)
  range.setEnd(last.node, last.offset + 1)
  return range
}

/** Mark text segments individually so selections crossing emphasis retain valid paragraph markup. */
export function markQuote(container: HTMLElement, quote: string, key: string): HTMLElement[] {
  const range = uniqueQuoteRange(container, quote)
  if (!range) return []
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const segments: { node: Text; start: number; end: number }[] = []
  let node: Node | null
  while ((node = walker.nextNode())) {
    if (!range.intersectsNode(node)) continue
    const start = node === range.startContainer ? range.startOffset : 0
    const end = node === range.endContainer ? range.endOffset : (node.textContent?.length ?? 0)
    if (end > start) segments.push({ node: node as Text, start, end })
  }
  return segments.map(({ node, start, end }, index) => {
    if (end < node.length) node.splitText(end)
    const text = start ? node.splitText(start) : node
    const mark = document.createElement('mark')
    mark.dataset.passage = key
    mark.tabIndex = index === 0 ? 0 : -1
    mark.setAttribute('role', 'button')
    mark.setAttribute('aria-label', `Open discussion: ${quote}`)
    text.replaceWith(mark)
    mark.append(text)
    return mark
  })
}

/** A passage is scoped to both its source and the revision actually quoted. */
export function passageKey(ref: MessageRef): string {
  return JSON.stringify([ref.entity, ref.id, normaliseQuote(ref.quote ?? ''), ref.content_sha256 ?? ''])
}
