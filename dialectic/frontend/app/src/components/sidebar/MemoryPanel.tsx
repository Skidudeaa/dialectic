import { useState } from 'react'
import type { Memory } from '../../types'
import './MemoryPanel.css'

interface MemoryPanelProps {
  memories: Memory[]
  onAddMemory: (key: string, content: string) => void
  onSetMemoryPromotion: (memoryId: string, promoted: boolean) => Promise<void>
}

export function MemoryPanel({
  memories,
  onAddMemory,
  onSetMemoryPromotion,
}: MemoryPanelProps) {
  const [key, setKey] = useState('')
  const [content, setContent] = useState('')
  const [pendingMemoryId, setPendingMemoryId] = useState<string | null>(null)
  const [promotionError, setPromotionError] = useState<string | null>(null)

  const handleAdd = () => {
    if (!key.trim() || !content.trim()) return
    onAddMemory(key.trim(), content.trim())
    setKey('')
    setContent('')
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
    <div>
      <div className="memory-form">
        <input
          type="text"
          value={key}
          onChange={e => setKey(e.target.value)}
          placeholder="Key (e.g., definition:truth)"
        />
        <textarea
          value={content}
          onChange={e => setContent(e.target.value)}
          placeholder="What should be remembered?"
          rows={2}
        />
        <button className="btn btn-secondary btn-full btn-sm" onClick={handleAdd}>Add Memory</button>
      </div>
      {promotionError && (
        <div className="memory-error" role="alert">{promotionError}</div>
      )}
      <div className="memory-list">
        {memories.filter(m => m.status === 'active').map(m => (
          <div key={m.id} className="memory-card">
            <div className="memory-key">{m.key}</div>
            <div className="memory-value">{m.content}</div>
            <div className="memory-meta">
              <div className="memory-version">
                v{m.version} &middot; {m.scope}
                {m.personally_promoted && <span> &middot; personal</span>}
              </div>
              <button
                type="button"
                className={`memory-promotion ${m.personally_promoted ? 'is-promoted' : ''}`}
                disabled={pendingMemoryId === m.id}
                aria-pressed={m.personally_promoted}
                onClick={() => void handlePromotion(m)}
              >
                {pendingMemoryId === m.id
                  ? 'Saving…'
                  : m.personally_promoted ? 'Demote' : 'Promote'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
