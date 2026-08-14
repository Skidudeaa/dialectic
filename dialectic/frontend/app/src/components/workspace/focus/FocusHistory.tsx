import type { FieldMark, FieldReview } from '../../../types/workspace.ts'
import { humanizeRelation } from '../fieldDisplay.ts'
import { ReviewChip } from '../ReviewChip.tsx'
import './Focus.css'

function relativeWhen(iso: string): string {
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return ''
  const days = Math.floor((Date.now() - then.getTime()) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days} days ago`
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

interface FocusHistoryProps {
  /** This mark's own review rows, oldest first — field_marks.py already
   *  sorts them this way; not re-sorted here (same stable-order rule the
   *  Field scene follows). */
  reviews: FieldReview[]
  /** The supersession lineage this mark's replacement chain carries —
   *  oldest last, same shape FieldScene's history disclosure uses. Empty
   *  for a mark that has never been corrected/split/merged. */
  lineage: FieldMark[]
}

/**
 * Review rows and supersession lineage (§7.4's Focus reveal list) — the
 * append-only trail a mark carries, never rewritten (§1.10). A mark with
 * neither renders nothing rather than an empty "History" heading — this
 * section is absent, not empty, when there is genuinely nothing to show.
 */
export function FocusHistory({ reviews, lineage }: FocusHistoryProps) {
  if (reviews.length === 0 && lineage.length === 0) return null
  return (
    <section className="focus-section" aria-label="History">
      <h3 className="focus-section-label">History</h3>
      {reviews.length > 0 && (
        <ul className="focus-history-reviews">
          {reviews.map((review) => (
            <li key={review.id} className="focus-history-review">
              <span className="focus-history-action">{review.action}</span>
              <span className="focus-history-when">{relativeWhen(review.created_at)}</span>
              {review.note && <p className="focus-history-note">&ldquo;{review.note}&rdquo;</p>}
            </li>
          ))}
        </ul>
      )}
      {lineage.length > 0 && (
        <ul className="focus-history-lineage">
          {lineage.map((ancestor) => (
            <li key={ancestor.id} className="focus-history-ancestor">
              <span>{ancestor.title || humanizeRelation(ancestor.relation)}</span>
              <ReviewChip review="superseded" />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
