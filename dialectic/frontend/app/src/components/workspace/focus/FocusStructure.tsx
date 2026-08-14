import type { FieldMark } from '../../../types/workspace.ts'
import { humanizeRelation } from '../fieldDisplay.ts'
import { ReviewChip } from '../ReviewChip.tsx'
import './Focus.css'

export interface FocusRelationItem {
  mark: FieldMark
  /** The OTHER end's display text — resolved by the caller from whatever
   *  title map it already has (§5.2: no second projection). */
  otherLabel: string
}

interface FocusStructureProps {
  incoming: FocusRelationItem[]
  outgoing: FocusRelationItem[]
  onOpen?: (mark: FieldMark) => void
}

function RelationList({
  items, verb, onOpen,
}: {
  items: FocusRelationItem[]
  verb: 'incoming' | 'outgoing'
  onOpen?: (mark: FieldMark) => void
}) {
  if (items.length === 0) return null
  return (
    <ul className={`focus-structure-list is-${verb}`}>
      {items.map(({ mark, otherLabel }) => {
        const body = (
          <>
            <span className="focus-structure-relation">{humanizeRelation(mark.relation)}</span>
            <span className="focus-structure-other">{verb === 'incoming' ? '← ' : '→ '}{otherLabel}</span>
            <ReviewChip review={mark.review} />
          </>
        )
        return (
          <li key={mark.id} className={`focus-structure-item is-${mark.review}`}>
            {onOpen ? (
              <button type="button" className="focus-structure-open" onClick={() => onOpen(mark)}>
                {body}
              </button>
            ) : body}
          </li>
        )
      })}
    </ul>
  )
}

/**
 * Incoming and outgoing relationships (§7.4's Focus reveal list) — every
 * mark that names this object as a subject (incoming), and, when the
 * selected object is itself a field_mark, every subject IT names
 * (outgoing). Provisional marks carry the dashed/opacity treatment via the
 * shared `.field-mark-row`-style state classes, same as the Field scene —
 * never color alone (§17.4).
 */
export function FocusStructure({ incoming, outgoing, onOpen }: FocusStructureProps) {
  if (incoming.length === 0 && outgoing.length === 0) return null
  return (
    <section className="focus-section" aria-label="Relationships">
      <h3 className="focus-section-label">Relationships</h3>
      {incoming.length > 0 && (
        <div className="focus-structure-group">
          <p className="focus-structure-group-label">Incoming</p>
          <RelationList items={incoming} verb="incoming" onOpen={onOpen} />
        </div>
      )}
      {outgoing.length > 0 && (
        <div className="focus-structure-group">
          <p className="focus-structure-group-label">Outgoing</p>
          <RelationList items={outgoing} verb="outgoing" onOpen={onOpen} />
        </div>
      )}
    </section>
  )
}
