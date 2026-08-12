import { useMemo, useState } from 'react'
import type { Memory } from '../../types'
import './MemoryPanel.css'

interface MemoryPanelProps {
  memories: Memory[]
  onAddMemory: (key: string, content: string) => void
  onSetMemoryPromotion: (memoryId: string, promoted: boolean) => Promise<void>
  onOpenIdentity?: () => void
}

type PaperKind = 'identity' | 'model' | 'thesis'

/**
 * Room memory as a dossier, not a dump. System slots (identity, user
 * models, thesis state) are papers — they already have a home in the AI
 * tab. Facts are what a human meant to remember.
 */
export function MemoryPanel({
  memories,
  onAddMemory,
  onSetMemoryPromotion,
  onOpenIdentity,
}: MemoryPanelProps) {
  const [key, setKey] = useState('')
  const [content, setContent] = useState('')
  const [composing, setComposing] = useState(false)
  const [query, setQuery] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [pendingMemoryId, setPendingMemoryId] = useState<string | null>(null)
  const [promotionError, setPromotionError] = useState<string | null>(null)

  const { facts, papers } = useMemo(() => {
    const active = memories.filter((memory) => memory.status === 'active')
    return {
      facts: active.filter((memory) => paperKind(memory.key) === null),
      papers: active.filter((memory) => paperKind(memory.key) !== null),
    }
  }, [memories])

  const visibleFacts = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return facts
    return facts.filter((memory) => (
      memory.key.toLowerCase().includes(needle)
      || memory.content.toLowerCase().includes(needle)
    ))
  }, [facts, query])

  const handleAdd = () => {
    if (!key.trim() || !content.trim()) return
    onAddMemory(key.trim(), content.trim())
    setKey('')
    setContent('')
    setComposing(false)
  }

  const handlePromotion = async (memory: Memory) => {
    setPendingMemoryId(memory.id)
    setPromotionError(null)
    try {
      await onSetMemoryPromotion(memory.id, !memory.personally_promoted)
    } catch (error) {
      setPromotionError(
        error instanceof Error ? error.message : 'Memory promotion failed',
      )
    } finally {
      setPendingMemoryId(null)
    }
  }

  return (
    <div className="memory-panel">
      <header className="memory-head">
        <h3>Memory</h3>
        <span className="memory-count">{facts.length}</span>
        {!composing && (
          <button
            type="button"
            className="btn btn-ghost btn-sm memory-remember"
            onClick={() => setComposing(true)}
          >
            Remember
          </button>
        )}
      </header>

      {composing && (
        <div className="memory-form">
          <input
            type="text"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Name this — e.g. gathering place"
            autoFocus
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="What should be remembered?"
            rows={3}
          />
          <div className="memory-form-actions">
            <button className="btn btn-secondary btn-sm" onClick={handleAdd}>Keep</button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => { setComposing(false); setKey(''); setContent('') }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {promotionError && (
        <div className="memory-error" role="alert">{promotionError}</div>
      )}

      {facts.length > 5 && (
        <input
          className="memory-find"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find a memory"
        />
      )}

      <div className="memory-list">
        {visibleFacts.length === 0 && (
          <p className="memory-empty">
            {query.trim() ? 'Nothing matches.' : 'Nothing remembered here yet.'}
          </p>
        )}
        {visibleFacts.map((memory) => (
          <FactCard
            key={memory.id}
            memory={memory}
            expanded={expandedId === memory.id}
            pending={pendingMemoryId === memory.id}
            onToggle={() => setExpandedId((id) => (id === memory.id ? null : memory.id))}
            onPromote={() => void handlePromotion(memory)}
          />
        ))}
      </div>

      {papers.length > 0 && (
        <section className="memory-papers">
          <h4>Claude&rsquo;s papers</h4>
          {papers.map((memory) => {
            const kind = paperKind(memory.key)
            const openIdentity = kind === 'identity' && onOpenIdentity
            return (
              <button
                key={memory.id}
                type="button"
                className="memory-paper"
                onClick={() => {
                  if (openIdentity) onOpenIdentity()
                  else setExpandedId((id) => (id === memory.id ? null : memory.id))
                }}
              >
                <span className="memory-paper-title">{memoryTitle(memory.key)}</span>
                <span className="memory-paper-meta">v{memory.version}</span>
                {expandedId === memory.id && kind !== 'identity' && (
                  <span className="memory-paper-preview">{oneLine(memory.content, 220)}</span>
                )}
              </button>
            )
          })}
        </section>
      )}
    </div>
  )
}

function FactCard({ memory, expanded, pending, onToggle, onPromote }: {
  memory: Memory
  expanded: boolean
  pending: boolean
  onToggle: () => void
  onPromote: () => void
}) {
  const long = memory.content.length > 220
  return (
    <article className={`memory-card${expanded ? ' is-open' : ''}`}>
      <button type="button" className="memory-card-main" onClick={onToggle}>
        <div className="memory-key">{memoryTitle(memory.key)}</div>
        <div className={`memory-value${expanded || !long ? '' : ' is-clamped'}`}>
          {memory.content}
        </div>
      </button>
      <div className="memory-meta">
        <div className="memory-version">
          v{memory.version}
          {memory.personally_promoted && <span> · personal</span>}
        </div>
        <button
          type="button"
          className={`memory-promotion${memory.personally_promoted ? ' is-promoted' : ''}`}
          disabled={pending}
          aria-pressed={memory.personally_promoted}
          onClick={onPromote}
        >
          {pending ? 'Saving…' : memory.personally_promoted ? 'Personal' : 'Promote'}
        </button>
      </div>
    </article>
  )
}

function paperKind(key: string): PaperKind | null {
  const lower = key.toLowerCase()
  if (lower.startsWith('llm_identity:')) return 'identity'
  if (lower.startsWith('user_model:')) return 'model'
  if (lower === 'thesis_state_current' || lower.startsWith('thesis_state')) return 'thesis'
  return null
}

function memoryTitle(key: string): string {
  const lower = key.toLowerCase()
  if (lower.startsWith('llm_identity:')) return "Claude's identity"
  if (lower.startsWith('user_model:')) return 'A participant model'
  if (lower === 'thesis_state_current') return 'Thesis state'
  return key.replace(/[_:]+/g, ' ').replace(/\s+/g, ' ').trim()
}

function oneLine(raw: string, max: number): string {
  const text = raw.replace(/\s+/g, ' ').trim()
  return text.length <= max ? text : `${text.slice(0, max).trimEnd()}…`
}
