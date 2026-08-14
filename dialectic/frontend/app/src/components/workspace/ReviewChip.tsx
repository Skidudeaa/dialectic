import type { FieldReviewState } from '../../types/workspace.ts'
import './fieldDisplay.css'

/**
 * The provisional/confirmed/contested/superseded encoding, never
 * color-only (§16.4, §17.4): every state carries this literal text chip
 * alongside whatever border/opacity treatment the caller's CSS class adds.
 *
 * Split out from fieldDisplay.ts (the pure helpers FieldScene and Focus
 * both import) into its own file: it is the one actual component in that
 * group, and react-refresh's "a file exports either components or
 * non-components, not both" rule means mixing it in with the plain
 * functions there breaks fast refresh for every file that imports from it.
 */
interface ReviewChipProps {
  review: FieldReviewState
  className?: string
}

export function ReviewChip({ review, className }: ReviewChipProps) {
  return (
    <span className={`field-review-chip is-${review}${className ? ` ${className}` : ''}`}>
      {review}
    </span>
  )
}
