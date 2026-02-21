import type { Thread } from '../../types'
import './ThreadPanel.css'

interface ThreadPanelProps {
  threads: Thread[]
  activeThreadId: string | null
  onThreadSelect: (threadId: string) => void
  onForkThread: () => void
}

export function ThreadPanel({ threads, activeThreadId, onThreadSelect, onForkThread }: ThreadPanelProps) {
  return (
    <div>
      <div className="thread-list">
        {threads.map(t => (
          <div
            key={t.id}
            className={`thread-card ${t.id === activeThreadId ? 'active' : ''}`}
            onClick={() => onThreadSelect(t.id)}
          >
            <div className="thread-card-title">{t.title ?? `Thread ${t.id.slice(0, 6)}`}</div>
            <div className="thread-card-meta">
              <span>{t.message_count} messages</span>
              {t.parent_thread_id && <span className="thread-card-fork-badge">fork</span>}
            </div>
          </div>
        ))}
      </div>
      <button className="btn btn-secondary btn-full btn-sm" onClick={onForkThread} style={{ marginTop: '0.5rem' }}>
        Fork from last message
      </button>
    </div>
  )
}
