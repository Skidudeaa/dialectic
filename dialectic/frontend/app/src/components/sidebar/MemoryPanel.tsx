import { useState } from 'react'
import type { Memory } from '../../types'
import './MemoryPanel.css'

interface MemoryPanelProps {
  memories: Memory[]
  onAddMemory: (key: string, content: string) => void
}

export function MemoryPanel({ memories, onAddMemory }: MemoryPanelProps) {
  const [key, setKey] = useState('')
  const [content, setContent] = useState('')

  const handleAdd = () => {
    if (!key.trim() || !content.trim()) return
    onAddMemory(key.trim(), content.trim())
    setKey('')
    setContent('')
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
      <div className="memory-list">
        {memories.filter(m => m.status === 'active').map(m => (
          <div key={m.id} className="memory-card">
            <div className="memory-key">{m.key}</div>
            <div className="memory-value">{m.content}</div>
            <div className="memory-version">v{m.version} &middot; {m.scope}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
