import { useCallback, useEffect, useRef, useState } from 'react'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import DOMPurify from 'dompurify'
import { api } from '../../lib/api'
import type { SearchResult } from '../../types'
import './SearchOverlay.css'

interface SearchOverlayProps {
  roomId: string
  onClose: () => void
  onJump: (result: SearchResult) => void
}

const DEBOUNCE_MS = 220

function speakerLabel(result: SearchResult): string {
  if (result.speaker_type === 'llm_primary') return PARTICIPANT_NAME
  if (result.speaker_type === 'llm_provoker') return 'Claude (Provoker)'
  if (result.speaker_type === 'llm_annotator') return 'Claude (Annotator)'
  if (result.speaker_type === 'system') return 'System'
  return result.sender_name
}

/**
 * Full-text search across the room's history.
 *
 * ARCHITECTURE: thin client over GET /messages/search, which has existed
 * (ranked, stemmed, with ts_headline snippets) since the schema was written and
 * had no caller.
 * WHY: "what did we decide about X" was previously answered by scrolling.
 */
export function SearchOverlay({ roomId, onClose, onJump }: SearchOverlayProps) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [status, setStatus] = useState<'idle' | 'searching' | 'done' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  // Guards against a slow early request overwriting a later, more specific one.
  const requestSeqRef = useRef(0)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const trimmed = query.trim()

  useEffect(() => {
    // An empty box has nothing to reset — the render below simply ignores any
    // previous results rather than clearing them from in here.
    if (!trimmed) return

    const seq = ++requestSeqRef.current
    const timer = window.setTimeout(() => {
      setStatus('searching')
      api.searchMessages(roomId, trimmed)
        .then((data) => {
          if (seq !== requestSeqRef.current) return
          setResults(data as SearchResult[])
          setActiveIndex(0)
          setStatus('done')
          setError(null)
        })
        .catch((err: unknown) => {
          if (seq !== requestSeqRef.current) return
          setError(err instanceof Error ? err.message : 'Search failed')
          setStatus('error')
        })
    }, DEBOUNCE_MS)

    return () => window.clearTimeout(timer)
  }, [trimmed, roomId])

  // Everything below keys off `trimmed`, so an emptied box falls back to the
  // idle state without any of it needing to be unwound.
  const showResults = Boolean(trimmed) && status === 'done'

  const handleKeyDown = useCallback((event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((i) => Math.min(i + 1, results.length - 1))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((i) => Math.max(i - 1, 0))
      return
    }
    if (event.key === 'Enter' && results[activeIndex]) {
      event.preventDefault()
      onJump(results[activeIndex])
    }
  }, [results, activeIndex, onJump, onClose])

  return (
    <div className="search-overlay-backdrop" onClick={onClose} role="presentation">
      <div
        className="search-overlay"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Search conversation"
      >
        <div className="search-input-row">
          <input
            ref={inputRef}
            className="search-input"
            type="text"
            placeholder="Search this room's history…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button className="search-close" onClick={onClose} aria-label="Close search">&times;</button>
        </div>

        <div className="search-results">
          {!trimmed && (
            <div className="search-note">Type to search everything said in this room.</div>
          )}
          {trimmed && status === 'error' && <div className="search-note search-note-error">{error}</div>}
          {trimmed && status === 'searching' && <div className="search-note">Searching&hellip;</div>}
          {showResults && results.length === 0 && (
            <div className="search-note">No messages match &ldquo;{trimmed}&rdquo;.</div>
          )}

          {showResults && results.map((result, index) => (
            <button
              key={result.id}
              className={`search-result ${index === activeIndex ? 'active' : ''}`}
              onClick={() => onJump(result)}
              onMouseEnter={() => setActiveIndex(index)}
            >
              <div className="search-result-meta">
                <span className="search-result-author">{speakerLabel(result)}</span>
                <span className="search-result-date">
                  {new Date(result.created_at).toLocaleDateString(undefined, {
                    month: 'short', day: 'numeric', year: 'numeric',
                  })}
                </span>
              </div>
              {/* The snippet is server-generated ts_headline with <mark> tags.
                  Sanitised rather than trusted: it embeds message content. */}
              <div
                className="search-result-snippet"
                dangerouslySetInnerHTML={{
                  __html: DOMPurify.sanitize(result.snippet, { ALLOWED_TAGS: ['mark'] }),
                }}
              />
            </button>
          ))}
        </div>

        <div className="search-hints">
          <span>&uarr;&darr; to move</span>
          <span>Enter to jump</span>
          <span>Esc to close</span>
        </div>
      </div>
    </div>
  )
}
