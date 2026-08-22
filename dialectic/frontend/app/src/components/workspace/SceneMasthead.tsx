import type { ImplementedWorkspaceScene } from '../../types'
import { SCENE_LABELS, SCENE_HINTS, SCENE_GLYPHS, SCENE_PRIMER } from './sceneIdentity'
import './SceneMasthead.css'

/**
 * SceneMasthead — the place-maker (2026-08-18, owner: "I don't know where I
 * am or why I'm there").
 *
 * Every scene opens by naming itself: a glyph plate, the scene name set large
 * in the scene's own accent color, and its purpose line promoted from the old
 * one-line switcher hint. Paired with the per-scene `--scene-accent` set in
 * WorkspaceSceneFrame.css, this is what makes the Library feel like a
 * different room than the Ledger instead of a different filter.
 *
 * The transcript surfaces (record, house) get the COMPACT variant — a single
 * quiet line — because the sheet is their identity and the masthead must not
 * push the conversation down.
 *
 * THE PRIMER, AND WHY IT IS A NATIVE <details> (2026-08-21, owner: "the user
 * needs to be able to see EVERYWHERE what the fuck is going on"): one clause
 * cannot answer "what do I DO here", and a paragraph printed on every scene
 * switch re-teaches a returning user forever. A disclosure is the shape that
 * serves both — closed it costs one small chip on a line that already exists,
 * open it is the whole orientation. `<details>` because the platform already
 * implements the toggle, the keyboard, the ARIA and the find-in-page reveal;
 * a hand-rolled useState version would be more code doing less.
 *
 * HOW THE COMPACT CONTRACT IS KEPT rather than ignored: the summary IS the
 * existing masthead row, so the closed state adds no line to Record or House —
 * the chip sits at the end of the row the name and purpose already occupy.
 * The body only takes space when a human opens it, and a second tap gives it
 * back. It is an ordinary block SIBLING of the summary — both are children of
 * the `<details>`, which is itself a block box — so when open it simply follows
 * in flow, indented by `padding-left: 54px` to sit under the text column rather
 * than under the glyph plate. No flex participation and no absolute
 * positioning, which is why the PassageMarker stacking-context scar is not
 * re-opened here. (An earlier draft of this comment claimed the body was a flex
 * item of `.scene-masthead-inner` taking a row via `flex-basis: 100%`. It is
 * not a child of that element and no such rule exists; the note is kept in the
 * negative because it sent one reader looking for CSS that was never written.)
 *
 * `key={scene}` remounts the disclosure on every scene change. Without it the
 * DOM node is reused and its `open` state — set by the user, not by React —
 * rides along, so opening the Field's primer would silently open the Ledger's
 * as well. Every scene starts closed and is opened on purpose.
 */

const COMPACT_SCENES = new Set<ImplementedWorkspaceScene>(['record', 'house'])

export function SceneMasthead({ scene }: { scene: ImplementedWorkspaceScene }) {
  const compact = COMPACT_SCENES.has(scene)
  return (
    <header className={`scene-masthead${compact ? ' scene-masthead-compact' : ''}`}>
      <details className="scene-masthead-primer" key={scene}>
        <summary className="scene-masthead-inner">
          <span className="scene-masthead-glyph" aria-hidden="true">{SCENE_GLYPHS[scene]}</span>
          <div className="scene-masthead-text">
            <h2 className="scene-masthead-name">{SCENE_LABELS[scene]}</h2>
            <p className="scene-masthead-purpose" aria-live="polite">{SCENE_HINTS[scene]}</p>
          </div>
          <span className="scene-masthead-more">
            What is this?<span className="scene-masthead-caret" aria-hidden="true">▾</span>
          </span>
        </summary>
        <p className="scene-masthead-primer-body">{SCENE_PRIMER[scene]}</p>
      </details>
    </header>
  )
}
