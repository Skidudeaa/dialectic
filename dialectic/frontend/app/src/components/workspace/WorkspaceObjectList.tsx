import type { WorkspaceObject } from '../../types/workspace.ts'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import './WorkspaceObjectList.css'

/**
 * One renderer for every kind the projection produces.
 *
 * ARCHITECTURE: the scenes are FILTERS over one projection, not seven bespoke
 * lists. A reading, a thesis and a dossier entry arrive in the same shape from
 * workspace_objects.py, so rendering them once means a new adapter kind appears
 * in its scene without a new component — and means the Library and the Ledger
 * cannot drift into looking like different products.
 *
 * WHAT IT DELIBERATELY DOES NOT DO: act. `available_actions` describes what a
 * surface MAY offer; Release 1 shipped the projection read-only and every write
 * still belongs to the entity's own endpoint. Rendering an action here as a
 * live button would put a second door on entities that already have one.
 * Navigation is the exception, and it goes through the caller's navigate — by
 * room and branch, never the server's destination string, which is Task Group
 * B's rule against a second destination writer.
 */

const ORIGIN_LABEL: Record<string, string> = {
  human: 'you',
  dialectic: PARTICIPANT_NAME,
  desk: 'the desk',
  system: 'the system',
}

/** What a human still owes this object — distinct from its own lifecycle. */
const REVIEW_LABEL: Record<string, string> = {
  awaiting_human: 'needs you',
  accepted: 'accepted',
  dismissed: 'dismissed',
  resolved: 'resolved',
  failed: 'did not complete',
}

function relativeDay(iso: string): string {
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return ''
  const days = Math.floor((Date.now() - then.getTime()) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days} days ago`
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

interface ObjectCardProps {
  object: WorkspaceObject
  onOpen?: (object: WorkspaceObject) => void
}

export function ObjectCard({ object, onOpen }: ObjectCardProps) {
  const origin = ORIGIN_LABEL[object.provenance.origin] ?? object.provenance.origin
  const review = REVIEW_LABEL[object.review_state]
  // A branch is the only navigable coordinate the card owns; without one there
  // is nowhere specific to go, so it does not pretend to be a link.
  const navigable = Boolean(onOpen && object.branch_id)

  const body = (
    <>
      <div className="object-card-head">
        <span className="object-card-title">{object.title}</span>
        {review && (
          <span
            className={`object-card-review is-${object.review_state}`}
            // Not colour alone: the label carries the meaning (§17.4).
          >
            {review}
          </span>
        )}
      </div>
      {object.summary && <p className="object-card-summary">{object.summary}</p>}
      <div className="object-card-foot">
        <span className="object-card-origin">
          {origin}
          {object.provenance.detail ? ` · ${object.provenance.detail}` : ''}
        </span>
        <span className="object-card-when">{relativeDay(object.updated_at)}</span>
      </div>
    </>
  )

  if (!navigable) {
    return <li className="object-card" data-kind={object.kind}>{body}</li>
  }
  return (
    <li className="object-card is-navigable" data-kind={object.kind}>
      <button
        type="button"
        className="object-card-open"
        onClick={() => onOpen?.(object)}
        aria-label={`Open ${object.title}`}
      >
        {body}
      </button>
    </li>
  )
}

interface WorkspaceObjectListProps {
  objects: WorkspaceObject[]
  onOpen?: (object: WorkspaceObject) => void
  /** Announced to assistive tech so the list is not an unlabelled group. */
  label: string
}

export function WorkspaceObjectList({ objects, onOpen, label }: WorkspaceObjectListProps) {
  return (
    <ul className="object-list" aria-label={label}>
      {objects.map((object) => (
        <ObjectCard key={object.id} object={object} onOpen={onOpen} />
      ))}
    </ul>
  )
}
