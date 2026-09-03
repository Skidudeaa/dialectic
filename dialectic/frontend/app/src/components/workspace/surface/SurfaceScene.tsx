import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Message, MessageAnchor, MessageRef, TradingSnapshot } from '../../../types'
import type { ThesisStructureEdge, ThesisStructureNode } from '../../../types/trading'
import type { TradingDeskState } from '../../../hooks/useTradingDesk.ts'
import type { GeoScopesState } from '../../../hooks/useGeoScopes.ts'
import type { FieldMarksState } from '../../../hooks/useFieldMarks.ts'
import { useWorldObservations } from '../../../hooks/useWorldObservations.ts'
import { api } from '../../../lib/api.ts'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'
import type { WorldObservation } from '../../../types/geo.ts'
import { ThesisDag, type DagVerb } from '../../trading/ThesisDag'
import type { MessageInputHandle } from '../../chat/MessageInput'
import { SceneEmpty } from '../SceneEmpty'
import { SurfaceAtlas } from './SurfaceAtlas'
import { SurfaceUpdates } from './SurfaceUpdates'
import { SurfaceConversation, type SurfaceComposer } from './SurfaceConversation'
import {
  WIDE_SHAPES, humanWordsByNode, refFocusId, toSurfaceMessages,
  type ConversationShape, type SurfaceAuthor,
} from './surfaceModel.ts'
import './Surface.css'

/**
 * The working surface (2026-09-02) — the owner's mock made real.
 *
 * ONE ROOM, FOUR PANES, SIDE BY SIDE: the causal graph with the last human
 * word on every node (ThesisDag, extended, not forked), the room's geography
 * with what the feeds saw inside it (SurfaceAtlas, an SVG — never Cesium
 * here), the conversation in one of four shapes (SurfaceConversation), and
 * the updates that arrived since the reader was last here (SurfaceUpdates).
 *
 * THE MECHANISM THAT TIES THEM: a message carries what it is ABOUT
 * (metadata.anchor — the focused node or a disputed edge) and what it
 * ATTACHES (metadata.refs — an update dropped onto a node). Nothing here
 * writes anywhere the Record does not: focusing a node sets the anchor the
 * composer sends; dropping an update stages a ref on the next message; the
 * participant's reply inherits the anchor server-side. No new table.
 *
 * IT RECOMPOSES. The trading desk hook, the geo hook and the Field hook are
 * the ones App already mounts; the composer is MessageInput with an
 * imperative insert; the graph is the Bench's own viewer with opt-in props.
 */
export interface SurfaceSceneProps {
  roomId: string
  roomName: string
  currentUserId: string
  messages: Message[]
  streamingId: string | null
  userNames: Record<string, string>
  unreadSince: string | null
  desk: TradingDeskState
  tradingConfig: TradingSnapshot | null
  geo: GeoScopesState
  fieldMarks: FieldMarksState
  composer: SurfaceComposer
  typingUsers: string[]
  activityLabel: string | null
  /** Open a workspace object in Focus (`reading:<id>`, `field_mark:<id>`, …). */
  onOpenObject: (objectId: string) => void
  onOpenWorld: () => void
  onOpenBench: () => void
  onFork: (messageId: string) => void
}

const OBSERVATION_HOURS = 48

/** Same freshness rule as the Bench: under an hour is fresh. */
function snapshotIsStale(timestamp?: string): boolean {
  if (!timestamp) return true
  const ageMs = Date.now() - new Date(timestamp).getTime()
  return !Number.isFinite(ageMs) || ageMs >= 60 * 60 * 1000
}

export function SurfaceScene({
  roomId, roomName, currentUserId, messages, streamingId, userNames, unreadSince,
  desk, tradingConfig, geo, fieldMarks, composer, typingUsers, activityLabel,
  onOpenObject, onOpenWorld, onOpenBench, onFork,
}: SurfaceSceneProps) {
  const [anchor, setAnchor] = useState<MessageAnchor | null>(null)
  const [pendingRefs, setPendingRefs] = useState<MessageRef[]>([])
  const [shape, setShape] = useState<ConversationShape>('stream')
  const [selectedUpdateId, setSelectedUpdateId] = useState<string | null>(null)
  const composerRef = useRef<MessageInputHandle>(null)

  const observations = useWorldObservations(roomId, OBSERVATION_HOURS)

  // The room's voice flags, read from the live gates — the header's
  // "Annotator silent" line must never say the opposite of what runs.
  const [flags, setFlags] = useState<{ annotator: boolean | null; addressed: boolean | null }>({
    annotator: null, addressed: null,
  })
  useEffect(() => {
    let cancelled = false
    api.getRoomCapabilities(roomId)
      .then((caps) => {
        if (cancelled) return
        setFlags({
          annotator: caps.annotator_enabled ?? null,
          addressed: caps.addressed_only ?? null,
        })
      })
      .catch(() => { if (!cancelled) setFlags({ annotator: null, addressed: null }) })
    return () => { cancelled = true }
  }, [roomId])

  const surfaceMessages = useMemo(
    () => toSurfaceMessages(messages, { userNames, currentUserId, unreadSince, streamingId }),
    [messages, userNames, currentUserId, unreadSince, streamingId],
  )
  const humanWords = useMemo(() => humanWordsByNode(surfaceMessages), [surfaceMessages])

  // The lanes' columns: every human who has a name here, the reader first.
  const humans = useMemo<SurfaceAuthor[]>(() => {
    const seen = new Map<string, SurfaceAuthor>()
    for (const m of surfaceMessages) {
      if (m.author.kind === 'human' && !seen.has(m.author.id)) seen.set(m.author.id, m.author)
    }
    for (const [id, name] of Object.entries(userNames)) {
      if (!seen.has(id)) {
        seen.set(id, { id, name, kind: 'human', glyph: name.charAt(0).toUpperCase() || '?', isSelf: id === currentUserId })
      }
    }
    return [...seen.values()].sort((a, b) => Number(b.isSelf) - Number(a.isSelf))
  }, [surfaceMessages, userNames, currentUserId])

  const structure = desk.structure.status === 'ready' ? desk.structure.data ?? null : null
  const nodeCount = structure?.nodes.length ?? 0
  const spokenCount = structure ? structure.nodes.filter((n) => humanWords[n.id]).length : 0

  const scopes = geo.status === 'ready' ? geo.projection.scopes : []
  const observationRows = useMemo(
    () => (observations.status === 'ready' ? observations.projection.observations : []),
    [observations],
  )
  const counts = useMemo(
    () => (observations.status === 'ready' ? observations.projection.counts : []),
    [observations],
  )
  const fireHeadline = useMemo(() => {
    const fires = counts.filter((row) => row.layer === 'fires' && (row.novel ?? 0) > 0)
    if (fires.length === 0) return null
    const top = fires.reduce((best, row) => ((row.novel ?? 0) > (best.novel ?? 0) ? row : best))
    const total = fires.reduce((sum, row) => sum + (row.novel ?? 0), 0)
    return { total, scope: top.scope_label }
  }, [counts])
  const marks = fieldMarks.status === 'ready' ? fieldMarks.marks : []

  // ── Verbs on the focused node ────────────────────────────────────────
  const focusNode = useCallback((node: ThesisStructureNode | null) => {
    setAnchor(node ? { kind: 'node', id: node.id, label: node.label } : null)
  }, [])
  const verbs = useMemo<DagVerb[]>(() => [
    { label: 'Speak to it', run: () => composerRef.current?.focus() },
    { label: `Ask ${PARTICIPANT_NAME}`, run: () => composerRef.current?.insert(`@${PARTICIPANT_NAME} `) },
    { label: 'Dispute', run: (node) => composerRef.current?.insert(`I dispute ${node.label}: `) },
    { label: 'Bench ↗', run: () => onOpenBench() },
  ], [onOpenBench])
  const disputeEdge = useCallback((edge: ThesisStructureEdge) => {
    const label = (id: string) => structure?.nodes.find((n) => n.id === id)?.label ?? id
    setAnchor({
      kind: 'edge',
      id: `${edge.source}->${edge.target}`,
      label: `${label(edge.source)} → ${label(edge.target)}`,
    })
    composerRef.current?.insert(`Disputing "${edge.mechanism || 'this link'}": `)
  }, [structure])

  // ── Attaching an update to a node ────────────────────────────────────
  const stageRef = useCallback((ref: MessageRef, node?: ThesisStructureNode) => {
    if (node) setAnchor({ kind: 'node', id: node.id, label: node.label })
    setPendingRefs((refs) => (refs.some((r) => r.entity === ref.entity && r.id === ref.id) ? refs : [...refs, ref]))
    composerRef.current?.insert(`Evidence: ${ref.label} — `)
  }, [])
  const dropOnNode = useCallback((node: ThesisStructureNode, ref: MessageRef) => stageRef(ref, node), [stageRef])

  const openRef = useCallback((ref: MessageRef) => {
    const focusId = refFocusId(ref)
    if (focusId) onOpenObject(focusId)
    else if (ref.entity === 'world_observations') setSelectedUpdateId(ref.id)
    else if (ref.entity === 'geo_scopes') onOpenWorld()
  }, [onOpenObject, onOpenWorld])

  const selectObservation = useCallback((obs: WorldObservation | null) => {
    setSelectedUpdateId(obs ? obs.id : null)
  }, [])

  const wide = WIDE_SHAPES.has(shape)
  const unbound = desk.structure.status === 'empty' || (!desk.bound && desk.structure.status !== 'loading')

  return (
    <div className={`surf${wide ? ' surf--wide' : ''}`} data-testid="surface">
      <header className="surf-head">
        <div className="surf-head-identity">
          <span className="surf-head-title">
            <em>{structure?.meta.title ?? roomName}</em>
          </span>
          {tradingConfig?.revision != null && <span className="surf-head-coordinate">revision {tradingConfig.revision}</span>}
          {tradingConfig?.cascadePhase && (
            <span className="surf-head-coordinate">
              phase {tradingConfig.cascadePhase.number} · {tradingConfig.cascadePhase.key}
            </span>
          )}
        </div>
        {(structure || fireHeadline) && (
          <div className="surf-head-stats">
            {structure && (
              <span className="surf-head-stat">
                <b>{spokenCount}</b> of <b>{nodeCount}</b> nodes have a human word
              </span>
            )}
            {fireHeadline && (
              <span className="surf-head-stat surf-head-stat--hot">
                <b>{fireHeadline.total}</b> new fire{fireHeadline.total === 1 ? '' : 's'} in {fireHeadline.scope}
              </span>
            )}
          </div>
        )}
        {(flags.annotator !== null || flags.addressed !== null) && (
          <div className="surf-head-flags">
            {flags.annotator !== null && (
              <span className={`surf-head-flag${flags.annotator ? ' surf-head-flag--off' : ''}`}>
                Annotator {flags.annotator ? 'speaking' : 'silent · writes marks only'}
              </span>
            )}
            {flags.addressed !== null && (
              <span className={`surf-head-flag${flags.addressed ? '' : ' surf-head-flag--off'}`}>
                {PARTICIPANT_NAME} speaks {flags.addressed ? 'when addressed or a gate fires' : 'on its own judgment'}
              </span>
            )}
          </div>
        )}
        {structure && (
          <span className="surf-head-hint">
            click a node for verbs · click an edge to dispute it · drop an update onto a node
          </span>
        )}
      </header>

      <section className="surf-graph-pane" aria-label="Causal graph">
        {structure ? (
          <ThesisDag
            structure={structure}
            nodeStates={tradingConfig?.nodeStates}
            stale={snapshotIsStale(tradingConfig?.timestamp)}
            humanWords={humanWords}
            focusedNodeId={anchor?.kind === 'node' ? anchor.id : null}
            onFocusNode={focusNode}
            verbs={verbs}
            onDropRef={dropOnNode}
            onEdgeSelect={disputeEdge}
            height={380}
          />
        ) : unbound ? (
          <SceneEmpty
            kicker="Surface"
            headline="No thesis on this surface yet."
            action={<button type="button" className="btn btn-ghost btn-sm" onClick={onOpenBench}>Open the Bench</button>}
          >
            The graph appears once this room binds a thesis on the Bench; the conversation, the geography and the updates are already here.
          </SceneEmpty>
        ) : desk.structure.status === 'unavailable' ? (
          <SceneEmpty kicker="Surface" headline="The graph is unavailable.">{desk.structure.error ?? ''}</SceneEmpty>
        ) : (
          <SceneEmpty kicker="Surface" headline="Reading the graph…">{''}</SceneEmpty>
        )}
      </section>

      <section className="surf-atlas-pane" aria-label="Atlas">
        <SurfaceAtlas
          scopes={scopes}
          observations={observationRows}
          counts={counts}
          selectedId={selectedUpdateId}
          onSelect={selectObservation}
          onOpenWorld={scopes.length > 0 ? onOpenWorld : undefined}
          hours={OBSERVATION_HOURS}
        />
      </section>

      <SurfaceConversation
        roomId={roomId}
        messages={surfaceMessages}
        humans={humans}
        shape={shape}
        onShape={setShape}
        anchor={anchor}
        onClearAnchor={() => setAnchor(null)}
        onAnchor={setAnchor}
        pendingRefs={pendingRefs}
        onRemovePendingRef={(ref) => setPendingRefs((refs) => refs.filter((r) => !(r.entity === ref.entity && r.id === ref.id)))}
        onClearPendingRefs={() => setPendingRefs([])}
        composer={composer}
        composerRef={composerRef}
        typingUsers={typingUsers}
        activityLabel={activityLabel}
        onOpenRef={openRef}
        onFork={onFork}
        annotatorEnabled={flags.annotator}
        addressedOnly={flags.addressed}
      />

      <section className="surf-updates-pane" aria-label="Updates">
        <SurfaceUpdates
          roomId={roomId}
          since={unreadSince}
          observations={observationRows}
          marks={marks}
          selectedId={selectedUpdateId}
          onSelect={(ref) => setSelectedUpdateId(ref ? (ref.entity === 'world_observations' ? ref.id : refFocusId(ref) ?? ref.id) : null)}
          onOpen={openRef}
          onAttach={(ref) => stageRef(ref)}
          attachTargetLabel={anchor?.kind === 'node' ? anchor.label : null}
        />
      </section>
    </div>
  )
}
