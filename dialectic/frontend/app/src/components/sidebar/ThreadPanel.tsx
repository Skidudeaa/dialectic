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
    <div>
      {genealogyError && (
        <div className="thread-panel-error">
          Could not load the branch tree.
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
      <button className="btn btn-secondary btn-full btn-sm" onClick={onForkThread} style={{ marginTop: '0.5rem' }}>
        Fork from last message
      </button>
    </div>
  )
}
