import type { ImplementedWorkspaceScene } from '../../types'
import { SCENE_LABELS, SCENE_HINTS, SCENE_GLYPHS } from './sceneIdentity'
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
 */

const COMPACT_SCENES = new Set<ImplementedWorkspaceScene>(['record', 'house'])

export function SceneMasthead({ scene }: { scene: ImplementedWorkspaceScene }) {
  const compact = COMPACT_SCENES.has(scene)
  return (
    <header className={`scene-masthead${compact ? ' scene-masthead-compact' : ''}`}>
      <div className="scene-masthead-inner">
        <span className="scene-masthead-glyph" aria-hidden="true">{SCENE_GLYPHS[scene]}</span>
        <div className="scene-masthead-text">
          <h2 className="scene-masthead-name">{SCENE_LABELS[scene]}</h2>
          <p className="scene-masthead-purpose" aria-live="polite">{SCENE_HINTS[scene]}</p>
        </div>
      </div>
    </header>
  )
}
