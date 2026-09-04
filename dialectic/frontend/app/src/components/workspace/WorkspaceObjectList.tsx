import type { ReactNode } from 'react'
import type { WorkspaceObject, WorkspaceObjectKind } from '../../types/workspace.ts'
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

/** One small mark per kind, so a row's type reads off its shape, not off its
 *  position in the list. Decorative only — the title and origin carry the
 *  meaning, and the row announces itself through them. */
const KIND_GLYPHS: Record<WorkspaceObjectKind, ReactNode> = {
  reading: (
    <>
      <path d="M8 4.5C6.5 3.1 4.5 2.8 2.5 3v9.5c2-.2 4 .1 5.5 1.5 1.5-1.4 3.5-1.7 5.5-1.5V3c-2-.2-4 .1-5.5 1.5z" />
      <path d="M8 4.5V14" />
    </>
  ),
  research_brief: (
    <>
      <path d="M4 2.5h5L12 5.5v8H4z" />
      <path d="M9 2.5v3h3" />
      <path d="M6 8.5h4M6 11h4" />
    </>
  ),
  thesis: (
    <>
      <circle cx="4" cy="4.5" r="1.6" />
      <circle cx="12" cy="4.5" r="1.6" />
      <circle cx="8" cy="11.8" r="1.6" />
      <path d="M5.6 4.5h4.8M4.8 5.8l2.1 4.3M11.2 5.8l-2.1 4.3" />
    </>
  ),
  commitment: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M5.2 8.3l2 2 3.8-4.1" />
    </>
  ),
  proposal: (
    <>
      <path d="M2.5 10.5v3h11v-3" />
      <path d="M8 2.5v7M5.2 6.7L8 9.5l2.8-2.8" />
    </>
  ),
  dossier_entry: (
    <>
      <path d="M4.5 2.5h7v11h-7z" />
      <path d="M6.5 5.5h3M6.5 8h3M6.5 10.5h2" />
    </>
  ),
  house_movement: (
    <>
      <path d="M2.5 8L8 3l5.5 5" />
      <path d="M4.5 7.5V13h7V7.5" />
    </>
  ),
  record_event: (
    <>
      <path d="M3.4 11V8.3c0-1.9 1-3.1 2.8-3.6l.4 1.2c-1 .4-1.7 1.2-1.8 2.1h1.6V11z" fill="currentColor" stroke="none" />
      <path d="M9.4 11V8.3c0-1.9 1-3.1 2.8-3.6l.4 1.2c-1 .4-1.7 1.2-1.8 2.1h1.6V11z" fill="currentColor" stroke="none" />
    </>
  ),
  field_mark: (
    <>
      <path d="M3 13l.7-2.6L10 4.1l1.9 1.9-6.3 6.3z" />
      <path d="M9.4 4.7l1.9 1.9" />
    </>
  ),
}

/** The stamp inside a review chip — the word stays, the mark lets the state
 *  be read at a glance without memorising hues (§17.4: never colour alone). */
const REVIEW_MARKS: Record<string, ReactNode> = {
  awaiting_human: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 4.8V8l2.4 1.6" />
    </>
  ),
  accepted: <path d="M4 8.4l2.6 2.6L12 5.4" />,
  dismissed: <path d="M5 5l6 6M11 5l-6 6" />,
  resolved: (
    <>
      <path d="M3.6 8.4l2.6 2.6L11.6 5.6" />
      <path d="M3.5 13.4h9" />
    </>
  ),
  failed: (
    <>
      <path d="M8 3.2L14 13H2z" />
      <path d="M8 7v3M8 11.6v.2" />
    </>
  ),
}

/** The supersession mark on a retired entry — a rewind arrow, "history kept". */
const SUPERSEDED_MARK = (
  <>
    <path d="M12.8 8a4.8 4.8 0 1 1-1.4-3.4" />
    <path d="M12.9 2.2v2.6h-2.6" />
  </>
)

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
  const reviewMark = REVIEW_MARKS[object.review_state]
  // A branch is the only navigable coordinate the card owns; without one there
  // is nowhere specific to go, so it does not pretend to be a link.
  const navigable = Boolean(onOpen && object.branch_id)

  const body = (
    <>
      <div className="object-card-head">
        <span className="object-card-kind" aria-hidden="true">
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            {KIND_GLYPHS[object.kind]}
          </svg>
        </span>
        <span className="object-card-title">{object.title}</span>
        {review && (
          <span
            className={`object-card-review is-${object.review_state}`}
            // Not colour alone: the label carries the meaning (§17.4).
          >
            {reviewMark && (
              <svg
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                {reviewMark}
              </svg>
            )}
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
        {object.status === 'superseded' && (
          <span className="object-card-status is-superseded">
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              {SUPERSEDED_MARK}
            </svg>
            superseded
          </span>
        )}
        <span className="object-card-when">{relativeDay(object.updated_at)}</span>
      </div>
    </>
  )

  if (!navigable) {
    return (
      <li className="object-card" data-kind={object.kind} data-status={object.status}>
        {body}
      </li>
    )
  }
  return (
    <li className="object-card is-navigable" data-kind={object.kind} data-status={object.status}>
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
  // Callers guard the empty case with a scene-level empty state of their own;
  // this row exists so a projection that arrives empty still reads as an
  // intentional shelf, never a broken render.
  if (objects.length === 0) {
    return (
      <ul className="object-list" aria-label={label}>
        <li className="object-list-empty">
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M2.5 9.5l1.6-5h7.8l1.6 5" />
            <path d="M2.5 9.5h3.4l.9 1.6h2.4l.9-1.6h3.4v4h-11z" />
          </svg>
          <span>Nothing filed under this heading yet.</span>
        </li>
      </ul>
    )
  }
  return (
    <ul className="object-list" aria-label={label}>
      {objects.map((object) => (
        <ObjectCard key={object.id} object={object} onOpen={onOpen} />
      ))}
    </ul>
  )
}
