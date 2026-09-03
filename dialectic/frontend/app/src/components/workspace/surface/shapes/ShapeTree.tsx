import { useMemo, useState } from 'react'
import type { MessageRef } from '../../../../types'
import { refGlyph, type SurfaceMsg } from '../surfaceModel'
import { SurfaceMessage } from './SurfaceMessage'
import './shapes.css'

export interface ShapeTreeProps {
  messages: SurfaceMsg[]
  onOpenRef: (ref: MessageRef) => void
  onReply?: (id: string) => void
  onFork?: (id: string) => void
}

type ChildrenMap = Map<string, SurfaceMsg[]>

/** roots = parentId null, OR parentId pointing at a message not in this
 *  window — defensive, even though surfaceModel already nulls those. */
function buildForest(messages: SurfaceMsg[]): { roots: SurfaceMsg[]; childrenOf: ChildrenMap } {
  const byId = new Map(messages.map((m) => [m.id, m]))
  const childrenOf: ChildrenMap = new Map()
  const roots: SurfaceMsg[] = []
  for (const m of messages) {
    if (m.parentId && byId.has(m.parentId)) {
      const siblings = childrenOf.get(m.parentId) ?? []
      siblings.push(m)
      childrenOf.set(m.parentId, siblings)
    } else {
      roots.push(m)
    }
  }
  return { roots, childrenOf }
}

function countDescendants(id: string, childrenOf: ChildrenMap): number {
  const kids = childrenOf.get(id) ?? []
  return kids.reduce((sum, k) => sum + 1 + countDescendants(k.id, childrenOf), 0)
}

/** Every ref used anywhere in a root's subtree, deduped by entity:id. */
function collectRefs(id: string, childrenOf: ChildrenMap, byId: Map<string, SurfaceMsg>): MessageRef[] {
  const msg = byId.get(id)
  if (!msg) return []
  const kids = childrenOf.get(id) ?? []
  return [...msg.refs, ...kids.flatMap((k) => collectRefs(k.id, childrenOf, byId))]
}

function TreeNode({
  msg, isReply, childrenOf, onOpenRef, onReply, onFork,
}: {
  msg: SurfaceMsg
  isReply: boolean
  childrenOf: ChildrenMap
  onOpenRef: (ref: MessageRef) => void
  onReply?: (id: string) => void
  onFork?: (id: string) => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const kids = childrenOf.get(msg.id) ?? []
  const branches = countDescendants(msg.id, childrenOf)

  return (
    <div className="surf-tree-node">
      <div className="surf-tree-row">
        {isReply && <span className="surf-tree-glyph" aria-hidden="true">↳</span>}
        <SurfaceMessage msg={msg} onOpenRef={onOpenRef} onReply={onReply} />
      </div>
      <div className="surf-tree-controls">
        <span className="surf-tree-branches">branches: {branches}</span>
        {kids.length > 0 && (
          <button type="button" onClick={() => setCollapsed((c) => !c)}>
            {collapsed ? 'restore' : 'prune'}
          </button>
        )}
        {onFork && (
          <button type="button" onClick={() => onFork(msg.id)}>fork</button>
        )}
      </div>
      {!collapsed && kids.length > 0 && (
        <div className="surf-tree-children">
          {kids.map((k) => (
            <TreeNode
              key={k.id}
              msg={k}
              isReply
              childrenOf={childrenOf}
              onOpenRef={onOpenRef}
              onReply={onReply}
              onFork={onFork}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * The claim-tree shape: one block per root message, replies nested beneath
 * their parent, with a merge-candidates list beneath the forest for objects
 * that more than one branch converged on independently.
 */
export function ShapeTree({ messages, onOpenRef, onReply, onFork }: ShapeTreeProps) {
  const { roots, childrenOf } = useMemo(() => buildForest(messages), [messages])
  const byId = useMemo(() => new Map(messages.map((m) => [m.id, m])), [messages])

  const mergeCandidates = useMemo(() => {
    const perRoot = roots.map((root) => {
      const map = new Map<string, MessageRef>()
      for (const ref of collectRefs(root.id, childrenOf, byId)) {
        map.set(`${ref.entity}:${ref.id}`, ref)
      }
      return map
    })
    const tally = new Map<string, { ref: MessageRef; count: number }>()
    for (const map of perRoot) {
      for (const [key, ref] of map) {
        const existing = tally.get(key)
        tally.set(key, { ref, count: (existing?.count ?? 0) + 1 })
      }
    }
    return [...tally.values()].filter((v) => v.count > 1)
  }, [roots, childrenOf, byId])

  return (
    <div className="surf-tree">
      <div className="surf-tree-header">
        {roots.length} root claims · {messages.length - roots.length} replies · {mergeCandidates.length} merge candidates
      </div>
      {roots.map((root) => (
        <section key={root.id} className="surf-claim-tree">
          <div className="surf-claim-tree-label">CLAIM TREE</div>
          <TreeNode
            msg={root}
            isReply={false}
            childrenOf={childrenOf}
            onOpenRef={onOpenRef}
            onReply={onReply}
            onFork={onFork}
          />
        </section>
      ))}
      {mergeCandidates.length > 0 && (
        <div className="surf-merge-candidates">
          <div className="surf-merge-header">MERGE CANDIDATES — branches reconverging on shared objects</div>
          <ul>
            {mergeCandidates.map(({ ref, count }) => (
              <li key={`${ref.entity}:${ref.id}`}>
                {refGlyph(ref.entity)} {ref.label} — {count} trees
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
