import { Suspense, lazy, useCallback, useMemo, useState } from 'react'
import type { AtlasState } from '../../../hooks/useAtlas.ts'
import type {
  AtlasEdge,
  AtlasGeoScope,
  AtlasNode,
  CausalGeoBinding,
} from '../../../types/atlas.ts'
import { isAtlasObjectNode } from '../../../types/atlas.ts'
import type { WorldSignal, WorldSignalSources } from '../../../types/geo.ts'
import { api } from '../../../lib/api.ts'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'
import { SceneEmpty, SceneLoading, SceneUnavailable } from '../SceneEmpty'
import { SourceState } from '../world/SourceState'
import {
  decodeWorldView, encodeWorldView, isWorldView, type WorldCamera,
} from '../world/worldCamera.ts'
import {
  AUTHORITY_LABEL, KIND_LABEL as SCOPE_KIND_LABEL, scopeDestination, scopeNode,
} from '../world/worldScopes.ts'
import { CausalBindingList } from '../world/CausalBindingList.tsx'
import './AtlasScene.css'
import '../world/World.css'

/**
 * Atlas — the caller's own cross-room map (PLAN.md §5.4, design v2 §22).
 *
 * LIST/TREE FIRST AND COMPLETE (§1.4): rooms group branches group artifacts,
 * exactly the shape the projection already carries via `room_id`/`branch_id`
 * — no client-side re-derivation of what belongs where. This component stays
 * the complete, authoritative representation on its own.
 *
 * TWO MODES OF ONE PROJECTION (World Lens, 2026-08-25). `House` is the list
 * above. `World` is the SECOND rendering of the SAME data the backend always
 * reserved: the fenced `scopes` the projection now carries, drawn on a globe
 * that loads only when asked for (React.lazy → the cesium chunk). World never
 * replaces the list — the globe sits ABOVE it, the on-map rows beneath the
 * globe are the same scopes as text, and the full House tree still follows.
 * That is the accessibility, reduced-motion, small-screen and failed-WebGL
 * path, all at once, and it costs no second component.
 *
 * WHICH MODE is the `view` axis of the URL (`world[:camera]`), decoded here
 * by worldCamera.ts and written ONLY through `onView` → the one navigation
 * writer. This scene owns no router: a toggle is a navigate, a camera settle
 * is a navigate with 'replace'.
 *
 * WHY `onNavigate` is a caller-provided callback rather than an import: this
 * scene does not know about `useRoomNavigation` or the `object` axis. A
 * room/branch tap resolves to a `{ roomId, threadId }` destination; an
 * object-kind node tap (thesis, reading, research_brief, commitment,
 * field_mark) resolves to `{ roomId, threadId, object: id }` — Object ids
 * REUSE workspace-object id conventions (types/atlas.ts).
 */
export interface AtlasNavigateDestination {
  roomId: string
  threadId?: string | null
  object?: string | null
  messageId?: string | null
}

interface AtlasSceneProps {
  state: AtlasState
  onNavigate: (destination: AtlasNavigateDestination) => void
  /** The URL's `view` axis, verbatim; null = House mode. */
  view?: string | null
  /** Write a new view through the one navigation writer. */
  onView?: (view: string | null, mode: 'push' | 'replace') => void
  /** Bounded capabilities already authorized by the saved-room owner.
   * A signal without its exact room token stays visible but read-only. */
  signalRoomTokens?: ReadonlyMap<string, string>
  /** Refresh any room-local durable projection after placement. */
  onGeoChanged?: () => void
  /** The exact shared object axis; a Field mark may select its current scope. */
  selectedObjectId?: string | null
}

const WorldView = lazy(() => import('../world/WorldView'))

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

/** The scopes as rows — the same data the globe draws, readable without it.
 *  Every row says what it is, whose authority it carries, how fresh, and
 *  which room; a proposed scope reads as such rather than blending in. */
function OnTheMapGroup({
  scopes, nodesById, bindingsByScope, selectedScopeId, onNavigate,
}: {
  scopes: AtlasGeoScope[]
  nodesById: Map<string, AtlasNode>
  bindingsByScope: Map<string, CausalGeoBinding[]>
  selectedScopeId: string | null
  onNavigate: (d: AtlasNavigateDestination) => void
}) {
  if (scopes.length === 0) {
    return (
      <p className="world-note">
        Nothing is placed on the world yet. A room's Strait, a reading's
        region, a mark's location — each arrives as a scope a person confirmed
        or a source reported, never as a guess drawn by {PARTICIPANT_NAME}.
      </p>
    )
  }
  return (
    <section className="atlas-group" aria-label="On the map">
      <h3 className="atlas-group-title">On the map</h3>
      <ul className="atlas-list">
        {scopes.map((scope) => {
          const subject = scopeNode(scope, nodesById)
          const room = nodesById.get(`room:${scope.room_id}`)
          const selected = scope.id === selectedScopeId
          const causalBindings = bindingsByScope.get(scope.id) ?? []
          return (
            <li key={scope.id} className="atlas-row world-scope-row" data-kind={scope.kind} data-authority={scope.authority}>
              <button
                type="button"
                className="atlas-row-open"
                aria-current={selected ? 'true' : undefined}
                onClick={() => onNavigate(scopeDestination(scope))}
              >
                <span className="atlas-row-kind">{SCOPE_KIND_LABEL[scope.kind]}</span>
                <span className="atlas-row-title">
                  {scope.label || subject?.title || 'Unlabelled'}
                  {subject && subject.kind !== 'room' ? ` — ${subject.title}` : ''}
                </span>
                <span className="world-scope-meta">
                  <span>{AUTHORITY_LABEL[scope.authority]}</span>
                  <SourceState state={scope.source_state} observedAt={scope.observed_at ?? scope.retrieved_at} />
                  {room ? <span>{room.title}</span> : null}
                </span>
                {selected ? <span className="world-selected-chip">Selected</span> : null}
              </button>
              <CausalBindingList
                scopeLabel={scope.label || subject?.title || 'Unlabelled'}
                bindings={causalBindings}
                onOpenMark={(binding) => onNavigate({
                  roomId: binding.target.room_id,
                  object: binding.id,
                })}
              />
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function SignalRow({ signal, roomTitle, roomToken, onPlaced }: {
  signal: WorldSignal
  roomTitle?: string
  roomToken?: string
  onPlaced: () => void
}) {
  const [placing, setPlacing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const place = async () => {
    setPlacing(true)
    setError(null)
    try {
      if (!roomToken) return
      await api.placeWorldSignal(signal.room_id, signal.id, roomToken)
      onPlaced()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not place this signal')
    } finally {
      setPlacing(false)
    }
  }

  return (
    <li className="atlas-row world-signal-row" data-kind={signal.kind}>
      <div className="world-signal-body">
        <span className="atlas-row-kind">{signal.layer}</span>
        <span className="atlas-row-title">{signal.label || signal.source_id}</span>
        <span className="world-signal-meta">
          <span>{signal.provider}</span>
          <span>{signal.source_state}</span>
          <span>{signal.freshness}</span>
          <span>{signal.coverage}</span>
          {roomTitle ? <span>{roomTitle}</span> : null}
        </span>
        {roomToken ? (
          <button
            type="button"
            className="world-signal-place"
            disabled={placing}
            aria-label={`Place ${signal.label || signal.source_id}`}
            onClick={() => { void place() }}
          >
            {placing ? 'Placing…' : 'Place'}
          </button>
        ) : null}
      </div>
      {error ? <p className="world-signal-error" role="alert">{error}</p> : null}
    </li>
  )
}

/** Ephemeral observations are a separate read-only list, never disguised as
 * durable GeoScopes and never wired into Focus or review actions. */
function LiveSignalsGroup({ signals, sources, nodesById, signalRoomTokens, onPlaced }: {
  signals: WorldSignal[]
  sources: WorldSignalSources | undefined
  nodesById: Map<string, AtlasNode>
  signalRoomTokens: ReadonlyMap<string, string>
  onPlaced: () => void
}) {
  // A default/older Atlas response did not opt in. Preserve that contract by
  // rendering no invented source state.
  if (!sources) return null
  return (
    <section className="atlas-group world-signals" aria-label="Live signals">
      <h3 className="atlas-group-title">Live signals</h3>
      {sources.status === 'not_configured' ? (
        <p className="world-note">Live signal providers are not configured.</p>
      ) : (
        <>
          <ul className="world-source-list" aria-label="Signal sources">
            {sources.sources.map((source) => (
              <li key={source.provider}>
                <span>{source.provider}</span>
                <span>{source.source_state}</span>
                <span>{source.freshness}</span>
                <span>{source.coverage}</span>
              </li>
            ))}
          </ul>
          {signals.length === 0 ? (
            <p className="world-note">No current signals in your rooms.</p>
          ) : (
            <ul className="atlas-list">
              {signals.map((signal) => (
                <SignalRow
                  key={signal.id}
                  signal={signal}
                  roomTitle={nodesById.get(`room:${signal.room_id}`)?.title}
                  roomToken={signalRoomTokens.get(signal.room_id)}
                  onPlaced={onPlaced}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}

export function AtlasScene({
  state, onNavigate, view = null, onView,
  signalRoomTokens = new Map<string, string>(), onGeoChanged,
  selectedObjectId = null,
}: AtlasSceneProps) {
  const worldMode = isWorldView(view)
  const decoded = useMemo(() => decodeWorldView(view), [view])

  const onCameraSettle = useCallback((camera: WorldCamera) => {
    if (!onView) return
    onView(encodeWorldView({ camera, roomId: decoded?.roomId ?? null }), 'replace')
  }, [onView, decoded?.roomId])

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

  const { nodes, edges, scopes, signals = [], signal_sources: signalSources } = state.projection
  const causalBindings = state.projection.causal_bindings ?? []

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
  const selectedBinding = causalBindings.find((binding) => binding.id === selectedObjectId)
  const selectedScope = scopes.find((scope) => (
    scope.id === selectedObjectId
    || scope.lineage_root_id === selectedObjectId
    || scope.id === selectedBinding?.current_scope_id
  ))
  const bindingsByScope = new Map<string, CausalGeoBinding[]>()
  for (const binding of causalBindings) {
    const list = bindingsByScope.get(binding.current_scope_id) ?? []
    list.push(binding)
    bindingsByScope.set(binding.current_scope_id, list)
  }
  const focusScopes = decoded?.roomId ? scopes.filter((s) => s.room_id === decoded.roomId) : null
  const focusSignals = decoded?.roomId ? signals.filter((s) => s.room_id === decoded.roomId) : null
  const onSignalPlaced = () => {
    // useAtlas.retry is loading-safe: it invalidates an in-flight response
    // before requesting one projection containing both live and durable rows.
    state.retry()
    onGeoChanged?.()
  }

  const modes = onView ? (
    <div className="atlas-modes" role="group" aria-label="Atlas mode">
      <button
        type="button"
        className="atlas-mode"
        aria-pressed={!worldMode}
        onClick={() => onView(null, 'push')}
      >
        House
      </button>
      <button
        type="button"
        className="atlas-mode"
        aria-pressed={worldMode}
        onClick={() => onView(encodeWorldView({ camera: null, roomId: decoded?.roomId ?? null }), 'push')}
      >
        World
      </button>
    </div>
  ) : null

  return (
    <div className="scene-body atlas-scene" data-atlas-mode={worldMode ? 'world' : 'house'}>
      {modes}
      {worldMode ? (
        <Suspense fallback={<SceneLoading kicker="World" />}>
          <WorldView
            scopes={scopes}
            signals={signals}
            initialCamera={decoded?.camera ?? null}
            focusScopes={focusScopes}
            focusSignals={focusSignals}
            selectedScopeId={selectedScope?.id ?? null}
            onSelect={(scope) => onNavigate(scopeDestination(scope))}
            onCameraSettle={onCameraSettle}
          />
          {selectedScope ? (
            <section className="world-causal-overlay" aria-label="Selected causal evidence">
              <CausalBindingList
                scopeLabel={selectedScope.label || 'Unlabelled'}
                bindings={bindingsByScope.get(selectedScope.id) ?? []}
                onOpenMark={(binding) => onNavigate({
                  roomId: binding.target.room_id,
                  object: binding.id,
                })}
              />
            </section>
          ) : null}
        </Suspense>
      ) : null}
      <OnTheMapGroup
        scopes={scopes}
        nodesById={nodesById}
        bindingsByScope={bindingsByScope}
        selectedScopeId={selectedScope?.id ?? null}
        onNavigate={onNavigate}
      />
      {state.projection.causal_bindings_complete === false ? (
        <p className="world-note">
          {(state.projection.causal_bindings_omitted ?? 0).toLocaleString()} more causal bindings omitted.
        </p>
      ) : null}
      <LiveSignalsGroup
        signals={signals}
        sources={signalSources}
        nodesById={nodesById}
        signalRoomTokens={signalRoomTokens}
        onPlaced={onSignalPlaced}
      />
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
