import './Focus.css'

interface FocusHeaderProps {
  title: string
  /** e.g. "Field mark · Emerging position" or "Reading" — what this is,
   *  before what it says. */
  kindLabel: string
  onClose: () => void
}

/**
 * The title, in propositional serif (§16.5) — language itself is the object
 * of attention here, which is exactly what the serif voice is for. `onClose`
 * is the ONE control every Focus surface carries regardless of width: on
 * mobile it reads as Back, on desktop as Close, but it is the same action —
 * `navigate({…, object: null})` — so there is one control to test, not two.
 */
export function FocusHeader({ title, kindLabel, onClose }: FocusHeaderProps) {
  return (
    <header className="focus-header">
      <button type="button" className="focus-close" onClick={onClose} aria-label="Close Focus">
        ‹ Back
      </button>
      <p className="focus-kind">{kindLabel}</p>
      <h2 className="focus-title">{title}</h2>
    </header>
  )
}
