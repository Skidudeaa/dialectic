import type { CausalGeoBinding } from '../../../types/atlas.ts'

interface CausalBindingListProps {
  scopeLabel: string
  bindings: CausalGeoBinding[]
  onOpenMark: (binding: CausalGeoBinding) => void
}

function displayLabel(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

/** Exact Field semantics in DOM; never a fabricated geospatial primitive. */
export function CausalBindingList({
  scopeLabel, bindings, onOpenMark,
}: CausalBindingListProps) {
  if (bindings.length === 0) return null
  return (
    <ul className="world-causal-list" aria-label={`Causal bindings for ${scopeLabel}`}>
      {bindings.map((binding) => (
        <li key={binding.id} className="world-causal-binding">
          <span>{scopeLabel}</span>
          <span aria-hidden="true"> → </span>
          <button type="button" onClick={() => onOpenMark(binding)}>
            {displayLabel(binding.relation)}
          </button>
          <span aria-hidden="true"> → </span>
          <span>{binding.target.node_label}</span>
          <span className={`world-causal-review is-${binding.review_state}`}>
            {displayLabel(binding.review_state)}
          </span>
        </li>
      ))}
    </ul>
  )
}
