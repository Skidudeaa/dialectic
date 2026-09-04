import type { ThreadNode } from '../../types'
import { BranchTree } from './BranchTree'
import './ThreadPanel.css'

interface ThreadPanelProps {
  genealogy: ThreadNode[]
  genealogyError: boolean
  onRetryGenealogy: () => void
  activeThreadId: string | null
  onThreadSelect: (threadId: string) => void
  onForkThread: () => void
}

/**
 * The Branches panel — the same recursive BranchTree the rail renders,
 * full-size, above the existing fork action. A failed genealogy read
 * keeps the transcript untouched and offers a retry.
 */
export function ThreadPanel({
  genealogy,
  genealogyError,
  onRetryGenealogy,
  activeThreadId,
  onThreadSelect,
  onForkThread,
}: ThreadPanelProps) {
  return (
    <div className="thread-panel">
      <header className="thread-panel-head">
        <h3>Branch index</h3>
        {genealogy.length > 0 && (
          <span className="thread-panel-count">{countNodes(genealogy)} filed</span>
        )}
      </header>
      {genealogyError && (
        <div className="thread-panel-error" role="alert">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M12 9v4" /><path d="M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
          </svg>
          <span>Could not load the branch tree.</span>
          <button className="btn btn-ghost btn-sm" onClick={onRetryGenealogy}>
            Retry
          </button>
        </div>
      )}
      <BranchTree
        nodes={genealogy}
        activeThreadId={activeThreadId}
        onSelect={onThreadSelect}
      />
      <button className="btn btn-secondary btn-full btn-sm thread-fork-btn" onClick={onForkThread}>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M6 3v12" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 01-9 9" />
        </svg>
        Fork from last message
      </button>
    </div>
  )
}

function countNodes(nodes: ThreadNode[]): number {
  return nodes.reduce((total, node) => total + 1 + countNodes(node.children), 0)
}
