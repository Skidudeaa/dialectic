import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ContextInspector, ReviewButton } from '@dark-roast/companion-ui'
import type { MessageRef, ReadingDetail, ReadingLibraryResponse } from '../../../types'
import { api } from '../../../lib/api'
import { markQuote, readingAnchorFromSelection, MAX_READING_QUOTE_CHARS, MIN_QUOTE_CHARS, normaliseQuote } from '../../../lib/passageAnchor'
import { RenderedMarkdown } from '../focus/ReadingFocus'
import { passageKey, type SurfaceMsg } from './surfaceModel'

interface SurfaceEvidenceProps {
  roomId: string
  messages: SurfaceMsg[]
  selected: MessageRef | null
  onSelect: (ref: MessageRef | null) => void
  onDiscuss: (ref: MessageRef) => void
  onAttach?: (ref: MessageRef) => void
  onInvestigate?: (ref: MessageRef) => void
  onReply: (messageId: string) => void
  onJump: (messageId: string) => void
  onOpenFull: (ref: MessageRef) => void
  passages?: MessageRef[]
  onPassage?: (ref: MessageRef) => void
  scrollRequest?: number
}

/** Sources and the human exchanges they carry stay together while the room talks. */
export function SurfaceEvidence({ roomId, messages, selected, onSelect, onDiscuss, onAttach, onInvestigate, onReply, onJump, onOpenFull, passages, onPassage, scrollRequest = 0 }: SurfaceEvidenceProps) {
  const [query, setQuery] = useState('')
  const [library, setLibrary] = useState<ReadingLibraryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [detail, setDetail] = useState<ReadingDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [quote, setQuote] = useState('')
  const [quoteOccurrence, setQuoteOccurrence] = useState<number | undefined>()
  const [selectionPosition, setSelectionPosition] = useState<{ left: number; top: number; width: number; maxHeight: number } | null>(null)
  const [selectionError, setSelectionError] = useState<string | null>(null)
  const [passageNotice, setPassageNotice] = useState<string | null>(null)
  const sourceRef = useRef<HTMLDivElement>(null)
  const initialLibraryRoom = useRef<string | null>(null)
  const libraryRoom = useRef<string | null>(null)
  const selectedId = selected?.entity === 'reading_items' ? selected.id : null

  useEffect(() => {
    let cancelled = false
    const timer = window.setTimeout(() => {
      setError(null)
      setLibrary(null)
      api.getReadingLibrary(roomId, { q: query || undefined, limit: 40 })
        .then((result) => { if (!cancelled) { libraryRoom.current = roomId; setLibrary(result) } })
        .catch((cause: unknown) => { if (!cancelled) setError(cause instanceof Error ? cause.message : 'Could not load the sources') })
    }, query ? 180 : 0)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [roomId, query, attempt])

  useEffect(() => {
    if (!library || libraryRoom.current !== roomId || query || initialLibraryRoom.current === roomId) return
    initialLibraryRoom.current = roomId
    // Open an unambiguous starting source once, without trapping All sources.
    if (!selected && library.items.length === 1 && !library.next_before) {
      const item = library.items[0]
      onSelect({ entity: 'reading_items', id: item.id, label: item.title || item.url })
    }
  }, [library, query, roomId, selected, onSelect])

  useEffect(() => {
    let cancelled = false
    void Promise.resolve().then(async () => {
      if (cancelled) return
      setDetail(null)
      setDetailError(null)
      setQuote('')
      setQuoteOccurrence(undefined)
      setSelectionPosition(null)
      setSelectionError(null)
      if (!selectedId) return
      try {
        const result = await api.getReadingDetail(roomId, selectedId)
        // Older wire readings predate revision tracking. Fingerprint the
        // actual text without inventing a stored revision for them.
        const digest = result.content_sha256 ?? Array.from(new Uint8Array(
          await crypto.subtle.digest('SHA-256', new TextEncoder().encode(result.markdown)),
        ), (byte) => byte.toString(16).padStart(2, '0')).join('')
        if (!cancelled) setDetail({ ...result, content_sha256: digest })
      } catch (cause: unknown) {
        if (!cancelled) setDetailError(cause instanceof Error ? cause.message : 'Could not open this source')
      }
    })
    return () => { cancelled = true }
  }, [roomId, selectedId, attempt])

  const shared = useMemo(() => {
    const refs = new Map<string, MessageRef>()
    for (const message of [...messages].reverse()) {
      for (const ref of message.refs) {
        if (ref.entity === 'reading_items' && !refs.has(ref.id)) refs.set(ref.id, ref)
      }
    }
    return refs
  }, [messages])
  const items = useMemo(() => {
    const readings = new Map((library?.items ?? []).map((item) => [item.id, item]))
    const refs = query ? new Map<string, MessageRef>() : new Map(shared)
    for (const item of readings.values()) {
      if (!refs.has(item.id)) refs.set(item.id, { entity: 'reading_items', id: item.id, label: item.title || item.url })
    }
    return [...refs.values()].map((ref) => {
      const exchanges = messages.filter((message) => message.refs.some((r) => r.entity === ref.entity && r.id === ref.id))
      const people = [...new Set(exchanges.filter((m) => m.author.kind === 'human').map((m) => m.author.name))]
      return {
        id: ref.id, label: ref.label,
        description: people.length ? `${people.join(' · ')} · ${exchanges.length} contributions` : readings.get(ref.id)?.summary,
        onNavigate: () => onSelect({ ...ref, quote: undefined, quote_occurrence: undefined }),
      }
    })
  }, [library, shared, query, messages, onSelect])
  const exchanges = selected ? messages.filter((message) => message.refs.some((ref) => ref.entity === selected.entity && ref.id === selected.id)) : []
  const current = detail?.id === selectedId ? detail : null

  const selectedKey = selected?.quote ? passageKey(selected) : null
  // Incoming tokens and replies must not rebuild the article's text selection.
  const passageSignature = JSON.stringify(passages ?? [])
  const anchoredPassages = useMemo(() => JSON.parse(passageSignature) as MessageRef[], [passageSignature])
  useEffect(() => {
    const container = sourceRef.current
    if (!container || !current) return
    let lastScroll: string | null = null
    let pending = true
    const observer = new MutationObserver(() => { pending = true; paint() })
    function paint() {
      if (!pending) return
      const selection = window.getSelection()
      if (selection && !selection.isCollapsed && selection.rangeCount && container!.contains(selection.getRangeAt(0).commonAncestorContainer)) return
      pending = false
      observer.disconnect()
      for (const mark of container!.querySelectorAll('mark[data-passage]')) mark.replaceWith(...mark.childNodes)
      const marks: HTMLElement[] = []
      container!.normalize()
      const prose = container!.querySelector<HTMLElement>('.reading-focus-prose')
      const refs = new Map(anchoredPassages.filter((ref) => ref.id === current!.id && ref.quote).map((ref) => [passageKey(ref), ref]))
      if (selected?.quote) refs.set(passageKey(selected), selected)
      for (const [key, ref] of refs) {
        if (ref.content_sha256 && ref.content_sha256 !== current!.content_sha256) continue
        const painted = prose ? markQuote(prose, ref.quote!, key, ref.quote_occurrence) : []
        for (const mark of painted) {
          mark.dataset.active = String(key === selectedKey)
          if (!anchoredPassages.some((passage) => passageKey(passage) === key)) { mark.removeAttribute('role'); mark.removeAttribute('tabindex'); mark.removeAttribute('aria-label') }
        }
        marks.push(...painted)
      }
      const selectedMark = marks.find((mark) => mark.dataset.passage === selectedKey)
      setPassageNotice(selected?.quote && !selectedMark && container!.querySelector('.reading-focus-prose')
        ? 'This quote cannot be uniquely located in the current text. The original words remain attached to the thread.' : null)
      if (selectedMark && scrollRequest && lastScroll !== selectedKey) {
        const pane = container!.closest<HTMLElement>('.surf-evidence')!
        pane.scrollTop += selectedMark.getBoundingClientRect().top - pane.getBoundingClientRect().top - 110
        lastScroll = selectedKey
      }
      observer.observe(container!, { childList: true, subtree: true })
    }
    observer.observe(container, { childList: true, subtree: true })
    document.addEventListener('selectionchange', paint)
    const timer = window.setTimeout(paint, 0)
    return () => {
      window.clearTimeout(timer)
      observer.disconnect()
      document.removeEventListener('selectionchange', paint)
    }
  }, [current, anchoredPassages, selected, selectedKey, scrollRequest])

  function openPassage(event: React.MouseEvent | React.KeyboardEvent) {
    if ('key' in event && event.key !== 'Enter' && event.key !== ' ') return
    if (!('key' in event) && !window.getSelection()?.isCollapsed) return
    const mark = (event.target as HTMLElement).closest<HTMLElement>('mark[data-passage]')
    const ref = (passages ?? []).find((candidate) => passageKey(candidate) === mark?.dataset.passage)
    if (!ref) return
    event.preventDefault()
    onPassage?.(ref)
  }

  const readSelection = useCallback(() => {
    const container = sourceRef.current?.querySelector<HTMLElement>('.reading-focus-prose')
    if (!container) return
    const selection = window.getSelection()
    if (!selection || selection.isCollapsed || !selection.rangeCount || !container.contains(selection.getRangeAt(0).commonAncestorContainer)) {
      setQuote(''); setQuoteOccurrence(undefined); setSelectionError(null); setSelectionPosition(null)
      return
    }
    const raw = normaliseQuote(selection.toString())
    if (raw.length < MIN_QUOTE_CHARS) { setQuote(''); setQuoteOccurrence(undefined); setSelectionPosition(null); setSelectionError(null); return }
    const anchor = readingAnchorFromSelection(selection, container)
    setSelectionError(anchor ? null : raw.length > MAX_READING_QUOTE_CHARS
      ? `Select up to ${MAX_READING_QUOTE_CHARS} characters. Your selection has not been shortened.`
      : 'This selection could not be located exactly. Include its surrounding words.')
    setQuote(anchor?.quote ?? '')
    setQuoteOccurrence(anchor?.occurrence)
    const pane = container.closest('.surf-evidence')!.getBoundingClientRect()
    const range = selection.getRangeAt(0)
    const rect = typeof range.getBoundingClientRect === 'function' ? range.getBoundingClientRect() : pane
    const width = Math.min(340, pane.width - 24)
    const maxHeight = Math.min(180, pane.height - 16)
    setSelectionPosition({
      left: Math.max(pane.left + 12, Math.min(rect.left, pane.right - width - 12)),
      top: Math.max(pane.top + 8, Math.min(rect.bottom + 10, pane.bottom - maxHeight - 8)),
      width, maxHeight,
    })
  }, [])

  useEffect(() => {
    document.addEventListener('selectionchange', readSelection)
    window.addEventListener('resize', readSelection)
    const pane = sourceRef.current?.closest('.surf-evidence')
    pane?.addEventListener('scroll', readSelection)
    return () => {
      document.removeEventListener('selectionchange', readSelection)
      window.removeEventListener('resize', readSelection)
      pane?.removeEventListener('scroll', readSelection)
    }
  }, [readSelection, current])

  function discuss(attach = false, investigate = false) {
    if (!current) return
    setQuote('')
    setQuoteOccurrence(undefined)
    setSelectionPosition(null)
    window.getSelection()?.removeAllRanges()
    const submit = investigate && onInvestigate ? onInvestigate : attach && onAttach ? onAttach : onDiscuss
    submit({
      entity: 'reading_items', id: current.id, label: (current.title || current.url).slice(0, 200),
      ...(quote ? { quote, quote_occurrence: quoteOccurrence } : {}),
      ...(current.content_sha256 ? { content_sha256: current.content_sha256 } : {}),
    })
  }

  return (
    <aside className="surf-evidence" aria-label="Shared evidence">
      <div className="surf-evidence-heading">
        <span>On the table</span>
        {selected && <button type="button" onClick={() => onSelect(null)}>All sources</button>}
      </div>
      {selected ? (
        <div className="surf-evidence-selected">
          <h2>{current?.title || selected.label}</h2>
          {selected.quote && (passageNotice || !current || (selected.content_sha256 && selected.content_sha256 !== current.content_sha256)) && <blockquote className="surf-evidence-quoted">{selected.quote}</blockquote>}
          {passageNotice && <p className="surf-evidence-notice" role="status">{passageNotice}</p>}
          {selected.content_sha256 && current?.content_sha256 && selected.content_sha256 !== current.content_sha256 && (
            <p className="surf-evidence-notice">This source has changed since it was attached. {selected.quote
              ? 'The original quote stays with the contribution.' : 'You are viewing the current version.'}</p>
          )}
          <div className="surf-evidence-actions">
            {current && !quote && <ReviewButton intent="inspect" onClick={() => discuss(Boolean(onAttach))}>{onAttach ? 'Attach source to reply' : 'Discuss this source'}</ReviewButton>}
            {current && onAttach && <button type="button" onClick={() => discuss()}>Start a new thread</button>}
            <button type="button" onClick={() => onOpenFull(selected)}>Source details ↗</button>
            {current && /^https?:\/\//i.test(current.url) && <a href={current.url} target="_blank" rel="noopener noreferrer">Original ↗</a>}
          </div>
          {selectionPosition && <div className="surf-selection-action" style={selectionPosition} role="region" aria-label="Comment on selected passage"
            onPointerDown={(event) => event.preventDefault()}>
            {quote && <blockquote>{quote}</blockquote>}
            {selectionError && <p role="status">{selectionError}</p>}
            {quote && <button type="button" onClick={() => discuss(Boolean(onAttach))}>{onAttach ? 'Attach passage to reply' : 'Discuss this passage'}</button>}
            {quote && onInvestigate && <button type="button" onClick={() => discuss(false, true)}>Find and pull</button>}
            <button type="button" aria-label="Dismiss passage selection" onClick={() => { window.getSelection()?.removeAllRanges(); setSelectionPosition(null); setQuote(''); setQuoteOccurrence(undefined); setSelectionError(null) }}>×</button>
          </div>}
          {exchanges.length > 0 && <details className="surf-evidence-exchanges">
            <summary>{exchanges.length} contributions · {[...new Set(exchanges.map((m) => m.author.name))].join(' · ')}</summary>
            {exchanges.map((message) => (
              <div className="surf-evidence-exchange" key={message.id}>
                <button type="button" className="surf-evidence-word" onClick={() => onJump(message.id)}>
                  <b>{message.author.name}</b><time>{message.time}</time><span>{message.text.slice(0, 240)}{message.text.length > 240 ? '…' : ''}</span>
                </button>
                {message.author.kind !== 'system' && !message.isStreaming && <button type="button" onClick={() => onReply(message.id)}>Reply to {message.author.name}</button>}
              </div>
            ))}
          </details>}
          {detailError ? <p role="alert">{detailError} <button type="button" onClick={() => setAttempt((n) => n + 1)}>Retry</button></p>
            : selectedId && !current ? <p role="status">Opening the source…</p>
            : current ? <>
              <p className="surf-evidence-hint">Select a passage to discuss it. Your words and the complete quote travel together.</p>
              <div ref={sourceRef} className="surf-evidence-document" onPointerUp={readSelection} onKeyUp={readSelection} onClick={openPassage} onKeyDown={openPassage}>
                <RenderedMarkdown key={current.id + (current.content_sha256 ?? '')} markdown={current.markdown} />
              </div>
            </> : <p>Open the source details to inspect this evidence.</p>}
        </div>
      ) : <>
        <p className="surf-evidence-intro">Bring something into the conversation. The source and your responses stay together.</p>
        <label className="surf-evidence-search">Find a reading
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search the room’s library" />
        </label>
        {error && <p role="alert">{error} <button type="button" onClick={() => setAttempt((n) => n + 1)}>Retry</button></p>}
        {!library && !error && <p role="status">Reading the library…</p>}
        <ContextInspector title={query ? 'Matching sources' : shared.size ? 'Sources in this room' : 'Ready to discuss'} sources={items}
          empty={library && <p>{query ? 'No matching reading. Try another phrase.' : 'Paste an article link in the conversation or add a source to the Library.'}</p>} />
        {library?.next_before && <p className="surf-evidence-hint">Showing the latest 40. Search to find older sources.</p>}
      </>}
    </aside>
  )
}
