import { PARTICIPANT_NAME } from './productIdentity'

/**
 * Who a message names, and how that should read on the page.
 *
 * WHY this exists: `@amo` was plain text in the transcript. With two humans
 * you could infer the addressee from prose; with three you cannot, and the
 * room said so ("too hard to tell when users are talking to each other").
 *
 * WHY it decorates the SANITIZED DOM rather than the markdown source or the
 * raw HTML string: a string replace over HTML can land inside a tag or an
 * attribute, which is how a highlighter becomes an injection. Walking text
 * nodes after DOMPurify has run means the only thing this module can ever
 * introduce is a <span> of its own making, and code spans are skipped so an
 * `@example` in a snippet stays a snippet.
 */

// The participant's own handles. MUST agree with LLM_MENTION_RE in
// dialectic/llm/mentions.py, which decides whether the participant was
// addressed; this decides how the address is painted. Pinned by
// mentions.contract.test.ts.
export const PARTICIPANT_ALIASES = ['dialectic', 'claude', 'llm'] as const

export type MentionKind = 'participant' | 'human' | 'self'

export interface MentionContext {
  /** Display names of the room's humans, e.g. ['Amo', 'Dan', 'Scott']. */
  names: string[]
  /** The reader's own display name, if known — their mentions read loudest. */
  selfName?: string | null
}

// The left boundary is the same one the server uses: an email or a domain
// fragment (`amo@dialectic.example`) is not an address.
const MENTION_RE = /(?<![\w.+\-@])@([A-Za-z][\w-]*)/g

// Inside an address a handle that STARTS with an alias is the participant --
// `@llmThe` (a real message, the space lost to a fast thumb) is a summons, not
// a stranger. Same rule as addresses_someone_else() on the server.
function isParticipantHandle(handle: string): boolean {
  const lower = handle.toLowerCase()
  return PARTICIPANT_ALIASES.some((alias) => lower.startsWith(alias))
}

/**
 * Resolve one @handle. A handle matches a human when it is a prefix of their
 * display name's first word — "@dan" finds Dan, "@danw" does not — so a name
 * cannot be claimed by an unrelated longer handle.
 */
export function classifyMention(
  handle: string,
  ctx: MentionContext,
): { kind: MentionKind; label: string } | null {
  if (isParticipantHandle(handle)) {
    return { kind: 'participant', label: PARTICIPANT_NAME }
  }
  const lower = handle.toLowerCase()
  const match = ctx.names.find(
    (name) => name.trim().split(/\s+/)[0]?.toLowerCase() === lower,
  )
  if (!match) return null
  const isSelf =
    !!ctx.selfName &&
    ctx.selfName.trim().split(/\s+/)[0]?.toLowerCase() === lower
  return { kind: isSelf ? 'self' : 'human', label: match }
}

// Never decorate inside these: a handle in a code sample is sample text, and
// one inside an anchor is already a link doing its own job.
const SKIP_ANCESTORS = new Set(['CODE', 'PRE', 'A'])

function shouldSkip(node: Node): boolean {
  let el = node.parentElement
  while (el) {
    if (SKIP_ANCESTORS.has(el.tagName)) return true
    el = el.parentElement
  }
  return false
}

/**
 * Wrap every resolvable @mention in the already-sanitized HTML.
 *
 * Unresolvable handles are deliberately left as plain text: painting `@foo`
 * as a mention when the room has no foo tells the reader someone was
 * addressed who was not.
 */
export function decorateMentions(sanitizedHtml: string, ctx: MentionContext): string {
  if (!sanitizedHtml.includes('@')) return sanitizedHtml
  const template = document.createElement('template')
  template.innerHTML = sanitizedHtml

  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT)
  const targets: Text[] = []
  let current = walker.nextNode()
  while (current) {
    const text = current as Text
    if (text.data.includes('@') && !shouldSkip(text)) targets.push(text)
    current = walker.nextNode()
  }

  for (const text of targets) {
    const source = text.data
    MENTION_RE.lastIndex = 0
    const fragment = document.createDocumentFragment()
    let cursor = 0
    let match: RegExpExecArray | null
    let decorated = false

    while ((match = MENTION_RE.exec(source)) !== null) {
      const resolved = classifyMention(match[1], ctx)
      if (!resolved) continue
      if (match.index > cursor) {
        fragment.appendChild(
          document.createTextNode(source.slice(cursor, match.index)),
        )
      }
      const span = document.createElement('span')
      span.className = `mention mention-${resolved.kind}`
      span.textContent = match[0]
      span.title = resolved.label
      fragment.appendChild(span)
      cursor = match.index + match[0].length
      decorated = true
    }

    if (!decorated) continue
    if (cursor < source.length) {
      fragment.appendChild(document.createTextNode(source.slice(cursor)))
    }
    text.replaceWith(fragment)
  }

  return template.innerHTML
}

/**
 * The ADDRESS BLOCK: the leading run of @handles a message opens with.
 *
 * Mirrors `addresses_someone_else()` in dialectic/llm/mentions.py, which is
 * what rung 0 of the interjection ladder reads to decide whose turn it is.
 * The engine has been parsing this since 2026-08-15; the UI has never shown
 * it, so a reader had to infer from prose what the server already knew.
 */
const LEADING_ADDRESS_RE = /^\s*((?:@[A-Za-z][\w-]*[\s,:;]*)+)/
const HANDLE_RE = /@([A-Za-z][\w-]*)/g

export function addressBlock(content: string, ctx: MentionContext): string[] {
  if (!content) return []
  const match = LEADING_ADDRESS_RE.exec(content)
  if (!match) return []
  const labels: string[] = []
  HANDLE_RE.lastIndex = 0
  let handle: RegExpExecArray | null
  while ((handle = HANDLE_RE.exec(match[1])) !== null) {
    const resolved = classifyMention(handle[1], ctx)
    if (resolved && !labels.includes(resolved.label)) labels.push(resolved.label)
  }
  return labels
}
