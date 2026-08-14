import './Focus.css'

export interface FocusSourceItem {
  label: string
  /** Present only when this source resolved to something navigable. A
   *  source the caller could not place (e.g. a message outside the
   *  Record's cap) still lists its label — never dropped — but with no
   *  action, same as a non-navigable ObjectCard in WorkspaceObjectList. */
  onNavigate?: () => void
}

/**
 * Provenance, as a mono list (§16.5's provenance voice — identifiers,
 * timestamps, source chains). Every entry that CAN navigate does so through
 * the caller's own `navigate`, never a server-composed destination string —
 * the same rule WorkspaceObjectList already follows, so Focus cannot become
 * a second place that URL-grammar rule gets relitigated.
 */
export function FocusSources({ sources }: { sources: FocusSourceItem[] }) {
  if (sources.length === 0) return null
  return (
    <section className="focus-section" aria-label="Sources">
      <h3 className="focus-section-label">Sources</h3>
      <ul className="focus-sources-list">
        {sources.map((source, i) => (
          <li key={`${source.label}:${i}`}>
            {source.onNavigate ? (
              <button type="button" className="focus-source-link" onClick={source.onNavigate}>
                {source.label}
              </button>
            ) : (
              <span className="focus-source-plain">{source.label}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
