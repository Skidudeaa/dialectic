import type { ThreadNode } from '../../types'
import './BranchTree.css'

interface BranchTreeProps {
  nodes: ThreadNode[]
  activeThreadId: string | null
  onSelect: (threadId: string) => void
  compact?: boolean
}

/**
 * The ONE recursive fork tree — rendered compact beneath the active room
 * in the rail/drawer and full-size in the Branches panel, so the two
 * surfaces can never disagree about a room's genealogy. Depth drives a
 * bounded indentation custom property; children stay nested, never
 * flattened.
 */
export function BranchTree({ nodes, activeThreadId, onSelect, compact }: BranchTreeProps) {
  if (nodes.length === 0) return null
  return (
    <ul className={`branch-tree${compact ? ' branch-tree-compact' : ''}`}>
      {nodes.map((node) => (
        <BranchNode
          key={node.id}
          node={node}
          activeThreadId={activeThreadId}
          onSelect={onSelect}
        />
      ))}
    </ul>
  )
}

function BranchNode({ node, activeThreadId, onSelect }: {
  node: ThreadNode
  activeThreadId: string | null
  onSelect: (threadId: string) => void
}) {
  return (
    <li>
      <button
        className={`branch-node${node.id === activeThreadId ? ' active' : ''}`}
        style={{ '--branch-depth': Math.min(node.depth, 6) } as React.CSSProperties}
        onClick={() => onSelect(node.id)}
      >
        {node.parent_thread_id !== null && (
          <svg className="branch-fork-marker" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M6 3v12" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 01-9 9" />
          </svg>
        )}
        <span className="branch-node-title">
          {node.title ?? `Branch ${node.id.slice(0, 6)}`}
        </span>
        <span className="branch-node-count">{node.message_count}</span>
      </button>
      {node.children.length > 0 && (
        <ul className="branch-children">
          {node.children.map((child) => (
            <BranchNode
              key={child.id}
              node={child}
              activeThreadId={activeThreadId}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  )
}
