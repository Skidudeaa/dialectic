import { useState } from 'react'
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
  const [collapsed, setCollapsed] = useState(false)
  const isActive = node.id === activeThreadId
  const hasChildren = node.children.length > 0
  return (
    <li
      className={`branch-li${hasChildren ? ' has-children' : ''}${collapsed ? ' is-collapsed' : ''}`}
      style={{ '--branch-depth': Math.min(node.depth, 6) } as React.CSSProperties}
    >
      <div className="branch-row">
        {hasChildren ? (
          <button
            type="button"
            className="branch-toggle"
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand branch' : 'Collapse branch'}
            onClick={() => setCollapsed((value) => !value)}
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
        ) : (
          <span className="branch-toggle-spacer" aria-hidden="true" />
        )}
        <button
          className={`branch-node${isActive ? ' active' : ''}`}
          onClick={() => onSelect(node.id)}
          aria-current={isActive ? 'true' : undefined}
        >
          {node.parent_thread_id !== null && (
            <svg className="branch-fork-marker" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M6 3v12" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 01-9 9" />
            </svg>
          )}
          <span className="branch-node-title">
            {node.title ?? `Branch ${node.id.slice(0, 6)}`}
          </span>
          {isActive && (
            <span className="branch-here">
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
                <circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none" />
              </svg>
              you are here
            </span>
          )}
          <span className="branch-node-time" aria-hidden="true">{node.created_at.slice(0, 10)}</span>
          <span className="branch-node-count">
            <span className="branch-node-count-led" aria-hidden="true" />
            {node.message_count}
            <span className="sr-only"> messages</span>
          </span>
        </button>
      </div>
      {hasChildren && !collapsed && (
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
