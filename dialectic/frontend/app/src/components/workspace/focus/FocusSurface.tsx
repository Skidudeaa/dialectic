import { useMemo } from 'react'
import type { FieldReviewRequest, WorkspaceObject } from '../../../types/workspace.ts'
import type { WorkspaceObjectsState } from '../../../hooks/useWorkspaceObjects.ts'
import type { FieldMarksState } from '../../../hooks/useFieldMarks.ts'
import { SceneEmpty, SceneLoading } from '../SceneEmpty.tsx'
import {
  bareMarkId,
  buildObjectByCoordinate,
  buildObjectTitleMap,
  humanizeRelation,
  markLineage,
  resolveSubjectLabel,
} from '../fieldDisplay.ts'
import { FocusHeader } from './FocusHeader.tsx'
import { FocusAxes, type FocusAxis } from './FocusAxes.tsx'
import { FocusSources, type FocusSourceItem } from './FocusSources.tsx'
import { FocusStructure, type FocusRelationItem } from './FocusStructure.tsx'
import { FocusHistory } from './FocusHistory.tsx'
import { FocusActions } from './FocusActions.tsx'
import { FocusWorld } from './FocusWorld.tsx'
import type { GeoScopesState } from '../../../hooks/useGeoScopes.ts'
import './Focus.css'

interface FocusSurfaceProps {
  /** A workspace-object id, e.g. `field_mark:<uuid>` or `reading:<uuid>` —
   *  the SAME id space every WorkspaceObject and FieldMark already share. */
  objectId: string
  objects: WorkspaceObjectsState
  fieldMarks: FieldMarksState
  /** Membership gate for FocusActions — a guest identity (no JWT) never
   *  passes this, same boundary useFieldMarks/useWorkspaceObjects enforce
   *  by not fetching for one at all. */
  canAct: boolean
  /**
   * The ONE navigation primitive Focus needs, installed by the caller
   * (App.tsx) via useRoomNavigation.navigate — never a second destination
   * writer. Deliberately ONE function rather than three (close/select/open
   * branch): a source that both switches branch AND re-selects a different
   * object (FocusSources' click-through) is one destination change, not
   * two sequential navigate() calls racing two history pushes. `object` is
   * always explicit (never omitted) so every call site states its own
   * intent — closing clears it, selecting sets it, opening a branch alone
   * preserves whatever was already selected.
   */
  onNavigate: (target: { threadId?: string; object: string | null }) => void
  onReview: (markId: string, request: FieldReviewRequest) => Promise<void>
  /** World Lens: the room's geography, for the World section on a
   *  non-mark object. Optional so surfaces without a room (tests, guests)
   *  render exactly as before. */
  roomId?: string | null
  geo?: GeoScopesState
  onGeoChanged?: () => void
  onMarked?: () => void
}

const KIND_LABEL: Record<WorkspaceObject['kind'], string> = {
  reading: 'Reading',
  research_brief: 'Research brief',
  thesis: 'Thesis',
  commitment: 'Commitment',
  proposal: 'Proposal',
  dossier_entry: 'Dossier entry',
  house_movement: 'House movement',
  record_event: 'Record',
  field_mark: 'Field mark',
}

/**
 * The universal object inspector (design v2 §7.4) — a STATE, not a scene
 * (§5.2). Dispatches by kind: a field_mark gets the full three-axis Field
 * treatment (FocusStructure's incoming/outgoing, FocusHistory's lineage,
 * FocusActions' six review actions); every other kind gets the six
 * generically-buildable reveal items §7.4 scopes honestly (state, sources,
 * relationships, actions) without pretending to a review pipeline that only
 * field_marks has.
 *
 * An object id that does not resolve renders THIS surface's own unavailable
 * state, never a 404 (§1.18) — resolution is entirely client-side, against
 * whichever projection(s) the caller already fetched. No second fetch: the
 * whole point of "no universal artifact table" is that Focus reads what the
 * scenes already hold.
 */
export function FocusSurface({
  objectId, objects, fieldMarks, canAct, onNavigate, onReview,
  roomId = null, geo, onGeoChanged, onMarked,
}: FocusSurfaceProps) {
  const onClose = () => onNavigate({ object: null })
  const onSelectObject = (id: string) => onNavigate({ object: id })
  const isFieldMark = objectId.startsWith('field_mark:')

  // Hooks run unconditionally, before either early return below (rules of
  // hooks) — objectList/markList fall back to [] while their projection is
  // still loading or failed, which costs nothing: the two returns below
  // short-circuit on `stillLoading` before anything derived from an empty
  // list would be shown as if it were real.
  const objectList = useMemo(
    () => (objects.status === 'ready' ? objects.objects : []),
    [objects],
  )
  const markList = fieldMarks.status === 'ready' ? fieldMarks.marks : []
  const titles = useMemo(() => buildObjectTitleMap(objectList), [objectList])
  const byCoordinate = useMemo(() => buildObjectByCoordinate(objectList), [objectList])

  const stillLoading = objects.status === 'loading' || (isFieldMark && fieldMarks.status === 'loading')
  if (stillLoading) {
    return (
      <aside className="focus-surface" aria-label="Focus">
        <SceneLoading kicker="Focus" />
      </aside>
    )
  }

  const selectedMark = isFieldMark ? markList.find((m) => m.id === objectId) : undefined
  const selectedObject = !isFieldMark ? objectList.find((o) => o.id === objectId) : undefined

  if (!selectedMark && !selectedObject) {
    return (
      <aside className="focus-surface" aria-label="Focus">
        <button type="button" className="focus-close" onClick={onClose} aria-label="Close Focus">
          ‹ Back
        </button>
        <SceneEmpty kicker="Focus" headline="This isn't here to look at right now.">
          <p>
            The thing this pointed at may have moved past what this room
            keeps loaded, or a link named something no longer here. Nothing
            was deleted on your account of it.
          </p>
        </SceneEmpty>
      </aside>
    )
  }

  const title = selectedMark
    ? (selectedMark.title || humanizeRelation(selectedMark.relation))
    : (selectedObject?.title ?? '')
  const kindLabel = selectedMark
    ? `Field mark · ${humanizeRelation(selectedMark.relation)}`
    : KIND_LABEL[selectedObject?.kind ?? 'record_event']
  const branchId = selectedMark?.thread_id ?? selectedObject?.branch_id ?? null

  const axes: FocusAxis[] = selectedMark
    ? [
        { label: 'Origin', value: selectedMark.origin === 'inferred' ? 'Inferred' : 'Explicit' },
        { label: 'Review', value: selectedMark.review },
        { label: 'Deliberative status', value: humanizeRelation(selectedMark.deliberative_status) },
      ]
    : selectedObject
      ? [
          { label: 'Origin', value: humanizeRelation(selectedObject.provenance.origin) },
          { label: 'Review', value: humanizeRelation(selectedObject.review_state) },
          { label: 'Status', value: humanizeRelation(selectedObject.status) },
        ]
      : []

  const sources: FocusSourceItem[] = selectedMark
    ? selectedMark.subjects.map((subject) => {
        const resolved = byCoordinate.get(`${subject.entity}:${subject.id}`)
        return {
          label: resolveSubjectLabel(subject, titles),
          onNavigate: resolved?.branch_id
            ? () => onNavigate({ threadId: resolved.branch_id as string, object: resolved.id })
            : undefined,
        }
      })
    : (selectedObject?.relationships ?? []).map((r) => ({
        label: `${humanizeRelation(r.relation)}${r.entity !== 'url' ? ` · ${r.entity}` : ''}`,
      }))

  // Incoming: any mark whose subjects name this object's own coordinate(s).
  // Outgoing: only meaningful for a field_mark itself — its own subjects.
  const selectedCoordinates = selectedMark
    ? [{ entity: 'field_marks', id: bareMarkId(selectedMark.id) }]
    : (selectedObject?.source_entity ?? []).map((r) => ({ entity: r.entity, id: r.id }))

  const incoming: FocusRelationItem[] = markList.flatMap((m) => {
    if (selectedMark && m.id === selectedMark.id) return []
    const matches = m.subjects.some((s) => selectedCoordinates.some(
      (c) => c.entity === s.entity && c.id === s.id,
    ))
    return matches ? [{ mark: m, otherLabel: title }] : []
  })
  const outgoing: FocusRelationItem[] = selectedMark
    ? selectedMark.subjects.map((s) => ({ mark: selectedMark, otherLabel: resolveSubjectLabel(s, titles) }))
    : []

  const mergeCandidates = selectedMark
    ? markList.filter((m) => m.id !== selectedMark.id && m.review !== 'superseded')
    : []

  return (
    <aside className="focus-surface" aria-label="Focus">
      <FocusHeader title={title} kindLabel={kindLabel} onClose={onClose} />
      {branchId && (
        <button
          type="button"
          className="btn btn-ghost btn-sm focus-open-branch"
          onClick={() => onNavigate({ threadId: branchId, object: objectId })}
        >
          Open branch
        </button>
      )}
      <FocusAxes axes={axes} />
      <FocusSources sources={sources} />
      <FocusStructure incoming={incoming} outgoing={outgoing} onOpen={(m) => onSelectObject(m.id)} />
      {selectedObject && roomId && geo && (
        <FocusWorld
          roomId={roomId}
          object={selectedObject}
          geo={geo}
          canAct={canAct}
          onChanged={onGeoChanged ?? (() => undefined)}
          onMarked={onMarked ?? (() => undefined)}
        />
      )}
      {selectedMark && (
        <>
          <FocusHistory reviews={selectedMark.reviews} lineage={markLineage(selectedMark, markList)} />
          <FocusActions
            mark={selectedMark}
            canAct={canAct}
            mergeCandidates={mergeCandidates}
            onReview={(request) => onReview(selectedMark.id, request)}
          />
        </>
      )}
    </aside>
  )
}
