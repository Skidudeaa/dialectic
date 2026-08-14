import './Focus.css'

export interface FocusAxis {
  label: string
  value: string
}

/**
 * The epistemic dimensions, as text labels (§14.2) — never a single flattened
 * status. For a field_mark, the caller passes Origin/Review/Deliberative
 * status, THREE independent axes on purpose: confirmation must never read as
 * truth, and showing them side by side rather than collapsed into one word is
 * how that independence stays visible instead of merely documented. For any
 * other workspace-object kind, the caller passes whatever subset applies
 * (Origin/Review state/Status) — the component itself does not know or care
 * which kind it is rendering, only that every value gets a plain-text label.
 */
export function FocusAxes({ axes }: { axes: FocusAxis[] }) {
  if (axes.length === 0) return null
  return (
    <dl className="focus-axes" aria-label="State">
      {axes.map((axis) => (
        <div className="focus-axis" key={axis.label}>
          <dt>{axis.label}</dt>
          <dd>{axis.value}</dd>
        </div>
      ))}
    </dl>
  )
}
