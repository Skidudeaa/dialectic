import { ContextInspector } from '@dark-roast/companion-ui'
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
  return <ContextInspector title="Sources" className="focus-section" sources={sources.map((source, i) => ({ id: source.label + ':' + i, label: source.label, onNavigate: source.onNavigate }))} />
}
