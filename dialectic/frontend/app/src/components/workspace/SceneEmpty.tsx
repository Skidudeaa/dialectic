import type { ReactNode } from 'react'
import './SceneEmpty.css'

/**
 * The empty state, treated as a primary surface rather than a placeholder.
 *
 * WHY it carries this much weight: in production 12 of 23 rooms hold no message
 * at all, 20 hold no reading, and 15 hold no memory. Emptiness is not this
 * product's edge case — for most first visits it IS the room. Whatever a new
 * user learns about a scene, they learn here.
 *
 * So every empty scene answers four things in order: what this place is, what
 * lands here, how it gets here, and the one thing you can do about it now.
 * "Nothing yet" alone teaches nobody anything.
 */
interface SceneEmptyProps {
  /** Where you are. */
  kicker: string
  /** What is true right now, in a sentence. */
  headline: string
  /** What lands here and how it arrives. */
  children: ReactNode
  /** The on-ramp, when there is a real one. */
  action?: ReactNode
}

export function SceneEmpty({ kicker, headline, children, action }: SceneEmptyProps) {
  return (
    <div className="scene-empty" data-testid="scene-empty">
      <p className="scene-empty-kicker">{kicker}</p>
      <h3 className="scene-empty-headline">{headline}</h3>
      <div className="scene-empty-body">{children}</div>
      {action && <div className="scene-empty-action">{action}</div>}
    </div>
  )
}

/**
 * Not the same thing as empty, and design v2 §7.5 forbids letting it look like
 * it: "No empty automated run should be rendered as evidence that nothing
 * happened." A failed projection rendered as an empty shelf tells the reader
 * the room holds nothing, which is a claim we have no basis for.
 */
interface SceneUnavailableProps {
  kicker: string
  /** The thing that could not be read, named so the message is not generic. */
  what: string
  error?: string
  onRetry?: () => void
}

export function SceneUnavailable({ kicker, what, error, onRetry }: SceneUnavailableProps) {
  return (
    <div className="scene-empty scene-unavailable" data-testid="scene-unavailable">
      <p className="scene-empty-kicker">{kicker}</p>
      <h3 className="scene-empty-headline">Could not read {what}.</h3>
      <div className="scene-empty-body">
        <p>
          This is a failure to load, not an empty {what} — what is here is
          unknown until it loads.
        </p>
        {error && <p className="scene-empty-detail">{error}</p>}
      </div>
      {onRetry && (
        <div className="scene-empty-action">
          <button className="btn btn-secondary btn-sm" onClick={onRetry}>Try again</button>
        </div>
      )}
    </div>
  )
}

/** The shape a scene is in while it is still asking. Never "empty". */
export function SceneLoading({ kicker }: { kicker: string }) {
  return (
    <div className="scene-empty scene-loading" data-testid="scene-loading">
      <p className="scene-empty-kicker">{kicker}</p>
      <p className="scene-empty-body">Reading the room…</p>
    </div>
  )
}
