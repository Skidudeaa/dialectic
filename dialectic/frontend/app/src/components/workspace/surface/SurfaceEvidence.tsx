import { useEffect, useMemo, useRef, useState } from 'react'
import { ContextInspector, ReviewButton } from '@dark-roast/companion-ui'
import type { MessageRef, ReadingDetail, ReadingLibraryResponse } from '../../../types'
import { api } from '../../../lib/api'
import { anchorFromSelection, MAX_QUOTE_CHARS, normaliseQuote } from '../../../lib/passageAnchor'
import { RenderedMarkdown } from '../focus/ReadingFocus'
import type { SurfaceMsg } from './surfaceModel'

interface SurfaceEvidenceProps {
  roomId: string
  messages: SurfaceMsg[]
  selected: MessageRef | null
  onSelect: (ref: MessageRef | null) => void
  onDiscuss: (ref: MessageRef) => void
  onReply: (messageId: string) => void
  onJump: (messageId: string) => void
  onOpenFull: (ref: MessageRef) => void
}

/** Sources and the human exchanges they carry stay together while the room talks. */
export function SurfaceEvidence({ roomId, messages, selected, onSelect, onDiscuss, onReply, onJump, onOpenFull }: SurfaceEvidenceProps) {
  const [query, setQuery] = useState('')
  const [library, setLibrary] = useState<ReadingLibraryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [detail, setDetail] = useState<ReadingDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [quote, setQuote] = useState('')
  const [selectionError, setSelectionError] = useState<string | null>(null)
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
  }, [roomId, selectedId, selected?.quote, selected?.content_sha256, attempt])

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
        onNavigate: () => onSelect({ ...ref, quote: undefined }),
      }
    })
  }, [library, shared, query, messages, onSelect])
  const exchanges = selected ? messages.filter((message) => message.refs.some((ref) => ref.entity === selected.entity && ref.id === selected.id)) : []
  const current = detail?.id === selectedId ? detail : null

  function readSelection() {
    const container = sourceRef.current
    if (!container) return
    const selection = window.getSelection()
    const passage = anchorFromSelection(selection, container)
    setSelectionError(selection && normaliseQuote(selection.toString()).length > MAX_QUOTE_CHARS
      ? `Choose a passage of up to ${MAX_QUOTE_CHARS} characters.` : null)
    setQuote(passage?.quote ?? '')
  }

  function discuss() {
    if (!current) return
    onDiscuss({
      entity: 'reading_items', id: current.id, label: (current.title || current.url).slice(0, 200),
      ...(quote ? { quote } : {}),
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
          {selected.quote && <blockquote className="surf-evidence-quoted">{selected.quote}</blockquote>}
          {selected.content_sha256 && current?.content_sha256 && selected.content_sha256 !== current.content_sha256 && (
            <p className="surf-evidence-notice">This source has changed since it was attached. {selected.quote
              ? 'The original quote stays with the contribution.' : 'You are viewing the current version.'}</p>
          )}
          <div className="surf-evidence-actions">
            {current && <ReviewButton intent="inspect" onClick={discuss}>{quote ? 'Discuss this passage' : 'Discuss this source'}</ReviewButton>}
            <button type="button" onClick={() => onOpenFull(selected)}>Source details ↗</button>
          </div>
          {quote && <blockquote className="surf-evidence-selection">{quote}</blockquote>}
          {selectionError && <p role="status" className="surf-evidence-notice">{selectionError}</p>}
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
              <p className="surf-evidence-hint">Select a short passage to discuss it. Your words and the quote travel together.</p>
              <div ref={sourceRef} className="surf-evidence-document" onPointerUp={readSelection} onKeyUp={readSelection}>
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
