import { useState } from 'react'
import { api } from '../../lib/api'
import type { FieldMark } from '../../types/workspace.ts'
import { ReviewChip } from '../workspace/ReviewChip'
import './PassageMarker.css'

/**
 * The marks on one message, with the two review actions inline.
 *
 * WHY here and not only in Focus: confirm/contest/supersede have existed
 * since Release 3, with derived review state and multi-person confirms, and
 * production has 85 marks and ZERO human reviews. FieldScene's own comment
 * says it navigates rather than reviews, and Focus is two destinations away
 * from the conversation. The machinery was built and unreachable from where
 * people actually are. This surfaces it in the transcript; it does not add a
 * second voting system or a second vocabulary.
 *
 * Confirm and contest only. correct/split/merge reshape lineage and want the
 * room Focus gives them — offering them on a one-line row would invite a
 * consequential action with no space to see what it does.
 */
interface MessageMarksProps {
  roomId: string
  marks: FieldMark[]
  /** Told after a review lands so the caller can refresh the projection. */
  onReviewed?: () => void
}

export function MessageMarks({ roomId, marks, onReviewed }: MessageMarksProps) {
  const [busy, setBusy] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

  if (marks.length === 0) return null

  async function review(mark: FieldMark, action: 'confirm' | 'contest') {
    setBusy(mark.id)
    setFailed(null)
    try {
      await api.postFieldReview(roomId, markId(mark), { action })
      onReviewed?.()
    } catch {
      // A failed review must say so. Silently doing nothing reads as "my
      // confirm was recorded", which is the one thing it must never imply.
      setFailed(mark.id)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="msg-marks">
      {marks.map((mark) => (
        <div key={mark.id} className={`msg-mark is-${mark.review}`}>
          <span className="msg-mark-relation">{relationLabel(mark.relation)}</span>
          {mark.title && <span className="msg-mark-title">&ldquo;{mark.title}&rdquo;</span>}
          <ReviewChip review={mark.review} />
          {/* Confirming is not "this is true" — it is "this reading is
              right". The Field keeps those axes separate and so does this. */}
          <button
            type="button"
            className="msg-mark-action"
            disabled={busy === mark.id}
            onClick={() => review(mark, 'confirm')}
          >
            Confirm
          </button>
          <button
            type="button"
            className="msg-mark-action"
            disabled={busy === mark.id}
            onClick={() => review(mark, 'contest')}
          >
            Contest
          </button>
          {failed === mark.id && (
            <span className="msg-mark-error" role="status">not recorded — try again</span>
          )}
        </div>
      ))}
    </div>
  )
}

/** `FieldMark.id` is the workspace-object form; the review route wants the row. */
function markId(mark: FieldMark): string {
  return mark.id.startsWith('field_mark:') ? mark.id.slice('field_mark:'.length) : mark.id
}

function relationLabel(relation: string): string {
  return relation.replace(/_/g, ' ')
}
