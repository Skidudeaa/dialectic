import type { AtlasState } from '../../../hooks/useAtlas.ts'
import type { AtlasEdge, AtlasNode } from '../../../types/atlas.ts'
import { isAtlasObjectNode } from '../../../types/atlas.ts'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'
import { SceneEmpty, SceneLoading, SceneUnavailable } from '../SceneEmpty'
import './AtlasScene.css'

/**
 * Atlas — the caller's own cross-room map (PLAN.md §5.4, design v2 §22).
 *
 * LIST/TREE FIRST AND COMPLETE (§1.4): rooms group branches group artifacts,
 * exactly the shape the projection already carries via `room_id`/`branch_id`
 * — no client-side re-derivation of what belongs where. Any spatial view is
 * a LATER, second rendering of this SAME data (not built this release); this
 * component must stay the complete, authoritative representation on its own.
 *
 * WHY `onNavigate` is a caller-provided callback rather than an import: this
 * scene does not know about `useRoomNavigation` or the `object` axis it is
 * landing this release (TG-B/TG-E own that). A room/branch tap resolves to a
 * `{ roomId, threadId }` destination; an object-kind node tap (thesis,
 * reading, research_brief, commitment, field_mark) resolves to
 * `{ roomId, threadId, object: id }` — Object ids REUSE workspace-object id
 * conventions (types/atlas.ts), so the caller's navigate can hand this
 * straight to the object axis with no second id scheme to bridge.
 */
export interface AtlasNavigateDestination {
  roomId: string
  threadId?: string | null
  object?: string | null
}

interface AtlasSceneProps {
  state: AtlasState
  onNavigate: (destination: AtlasNavigateDestination) => void
}

const KIND_LABEL: Record<AtlasNode['kind'], string> = {
  room: 'Room',
  branch: 'Branch',
  thesis: 'Thesis',
  reading: 'Reading',
  research_brief: 'Research brief',
  commitment: 'Commitment',
  field_mark: 'Open question',
}

function nodeDestination(node: AtlasNode): AtlasNavigateDestination {
  if (node.kind === 'room') return { roomId: node.room_id }
  // A branch node's own `branch_id` IS the thread it represents (atlas_objects.py
  // sets it to the thread's own row id) -- no need to parse the `branch:<id>`
  // node id back apart.
  if (node.kind === 'branch') return { roomId: node.room_id, threadId: node.branch_id }
  return {
    roomId: node.room_id,
    threadId: node.branch_id,
    object: isAtlasObjectNode(node) ? node.id : null,
  }
}

function NodeRow({ node, onNavigate, depth = 0 }: {
  node: AtlasNode
  onNavigate: (d: AtlasNavigateDestination) => void
  depth?: number
}) {
  return (
    <li className="atlas-row" data-kind={node.kind} data-depth={depth}>
      <button
        type="button"
        className="atlas-row-open"
        onClick={() => onNavigate(nodeDestination(node))}
      >
        <span className="atlas-row-kind">{KIND_LABEL[node.kind]}</span>
        <span className="atlas-row-title">{node.title || 'Untitled'}</span>
        {node.due && <span className="atlas-row-due">due</span>}
      </button>
    </li>
  )
}

/** rooms → branches → their artifacts, in one pass over the flat node list —
 *  the projection already carries the grouping keys, so this is a sort, not
 *  a second source of truth about what belongs where. */
function buildTree(nodes: AtlasNode[]) {
  const rooms = nodes.filter((n) => n.kind === 'room')
  const branches = nodes.filter((n) => n.kind === 'branch')
  const artifacts = nodes.filter((n) => n.kind !== 'room' && n.kind !== 'branch')

  const branchesByRoom = new Map<string, AtlasNode[]>()
  for (const b of branches) {
    const list = branchesByRoom.get(b.room_id) ?? []
    list.push(b)
    branchesByRoom.set(b.room_id, list)
  }
  const artifactsByBranch = new Map<string, AtlasNode[]>()
  const artifactsByRoomOnly = new Map<string, AtlasNode[]>()
  for (const a of artifacts) {
    if (a.branch_id) {
      const list = artifactsByBranch.get(a.branch_id) ?? []
      list.push(a)
      artifactsByBranch.set(a.branch_id, list)
    } else {
      const list = artifactsByRoomOnly.get(a.room_id) ?? []
      list.push(a)
      artifactsByRoomOnly.set(a.room_id, list)
    }
  }
  return { rooms, branchesByRoom, artifactsByBranch, artifactsByRoomOnly }
}

function RoomSection({ room, branchesByRoom, artifactsByBranch, artifactsByRoomOnly, onNavigate }: {
  room: AtlasNode
  branchesByRoom: Map<string, AtlasNode[]>
  artifactsByBranch: Map<string, AtlasNode[]>
  artifactsByRoomOnly: Map<string, AtlasNode[]>
  onNavigate: (d: AtlasNavigateDestination) => void
}) {
  const branches = branchesByRoom.get(room.room_id) ?? []
  const roomOnly = artifactsByRoomOnly.get(room.room_id) ?? []
  return (
    <li className="atlas-room-section">
      <ul className="atlas-list">
        <NodeRow node={room} onNavigate={onNavigate} />
        {roomOnly.map((a) => <NodeRow key={a.id} node={a} onNavigate={onNavigate} depth={1} />)}
        {branches.map((b) => (
          <li key={b.id} className="atlas-branch-section">
            <ul className="atlas-list">
              <NodeRow node={b} onNavigate={onNavigate} depth={1} />
              {(artifactsByBranch.get(b.id) ?? []).map((a) => (
                <NodeRow key={a.id} node={a} onNavigate={onNavigate} depth={2} />
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </li>
  )
}

/** Echoes: citations that crossed a room boundary. Resolves a navigable
 *  destination only when the edge's target is itself a projected node
 *  (a branch or a room) -- a bare message reference is shown as text, never
 *  a dead link. */
function EchoesGroup({ edges, nodesById, onNavigate }: {
  edges: AtlasEdge[]
  nodesById: Map<string, AtlasNode>
  onNavigate: (d: AtlasNavigateDestination) => void
}) {
  const echoes = edges.filter((e) => e.kind === 'echo_citation')
  if (echoes.length === 0) return null
  return (
    <section className="atlas-group" aria-label="Echoes">
      <h3 className="atlas-group-title">Echoes</h3>
      <ul className="atlas-list">
        {echoes.map((edge, i) => {
          const targetNode = edge.target.entity === 'threads'
            ? nodesById.get(`branch:${edge.target.id}`)
            : edge.target.entity === 'rooms'
              ? nodesById.get(`room:${edge.target.id}`)
              : undefined
          const text = edge.label || 'A memory cited elsewhere'
          if (!targetNode) {
            return <li key={i} className="atlas-row atlas-row-static">{text}</li>
          }
          return (
            <li key={i} className="atlas-row">
              <button
                type="button"
                className="atlas-row-open"
                onClick={() => onNavigate(nodeDestination(targetNode))}
              >
                <span className="atlas-row-kind">Echo</span>
                <span className="atlas-row-title">{text} — {targetNode.title}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function UnresolvedGroup({ nodes, onNavigate }: {
  nodes: AtlasNode[]
  onNavigate: (d: AtlasNavigateDestination) => void
}) {
  const unresolved = nodes.filter((n) => n.kind === 'field_mark' || (n.kind === 'commitment' && n.due))
  if (unresolved.length === 0) return null
  return (
    <section className="atlas-group" aria-label="Unresolved work">
      <h3 className="atlas-group-title">Unresolved work</h3>
      <ul className="atlas-list">
        {unresolved.map((n) => <NodeRow key={n.id} node={n} onNavigate={onNavigate} />)}
      </ul>
    </section>
  )
}

function SharedSourcesGroup({ nodes, onNavigate }: {
  nodes: AtlasNode[]
  onNavigate: (d: AtlasNavigateDestination) => void
}) {
  const readings = nodes.filter((n) => n.kind === 'reading')
  if (readings.length === 0) return null
  return (
    <section className="atlas-group" aria-label="Shared sources">
      <h3 className="atlas-group-title">Shared sources</h3>
      <ul className="atlas-list">
        {readings.map((n) => <NodeRow key={n.id} node={n} onNavigate={onNavigate} />)}
      </ul>
    </section>
  )
}

export function AtlasScene({ state, onNavigate }: AtlasSceneProps) {
  if (state.status === 'loading') return <SceneLoading kicker="Atlas" />
  if (state.status === 'unavailable') {
    return (
      <SceneUnavailable
        kicker="Atlas"
        what="the atlas"
        error={state.error}
        onRetry={state.retry}
      />
    )
  }

  const { nodes, edges } = state.projection

  if (nodes.length === 0) {
    return (
      <SceneEmpty kicker="Atlas" headline="Nothing to map yet.">
        <p>
          Atlas is the map of everywhere you can go — every room you belong
          to, its branches, and what each one holds: a thesis, a reading, a
          brief, a commitment, a question still open.
        </p>
        <p>
          It fills in as you join rooms and those rooms fill in — nothing is
          built here on its own. {PARTICIPANT_NAME} draws only the
          connections a real row backs: a branch's parent, a citation across
          rooms, a source an article came from.
        </p>
      </SceneEmpty>
    )
  }

  const { rooms, branchesByRoom, artifactsByBranch, artifactsByRoomOnly } = buildTree(nodes)
  const nodesById = new Map(nodes.map((n) => [n.id, n]))

  return (
    <div className="scene-body atlas-scene">
      <ul className="atlas-list atlas-room-list" aria-label="Rooms">
        {rooms.map((room) => (
          <RoomSection
            key={room.id}
            room={room}
            branchesByRoom={branchesByRoom}
            artifactsByBranch={artifactsByBranch}
            artifactsByRoomOnly={artifactsByRoomOnly}
            onNavigate={onNavigate}
          />
        ))}
      </ul>
      <UnresolvedGroup nodes={nodes} onNavigate={onNavigate} />
      <SharedSourcesGroup nodes={nodes} onNavigate={onNavigate} />
      <EchoesGroup edges={edges} nodesById={nodesById} onNavigate={onNavigate} />
    </div>
  )
}
