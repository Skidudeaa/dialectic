import type { ReactNode } from 'react'
import type { ImplementedWorkspaceScene } from '../../types'
import { SceneSwitcher, type SceneSignal } from './SceneSwitcher'
import { SceneMasthead } from './SceneMasthead'
import './WorkspaceSceneFrame.css'

interface WorkspaceSceneFrameProps {
  scene: ImplementedWorkspaceScene
  /**
   * What this destination may show, in switcher order, default first — from
   * `scenesForDestination`. It is PASSED IN rather than derived here on
   * purpose: the frame used to hardcode its own copy of the availability rule
   * ("only Home root has a House") while the router held a second copy, and two
   * copies of one rule is exactly how the participant name drifted three ways.
   */
  scenes: readonly ImplementedWorkspaceScene[]
  onSelect: (scene: ImplementedWorkspaceScene) => void
  /** Scene bodies, built by the caller. A missing scene renders the default. */
  content: Partial<Record<ImplementedWorkspaceScene, ReactNode>>
  /** Running-dot activity signals per scene tile — passed straight through. */
  signals?: Partial<Record<ImplementedWorkspaceScene, SceneSignal>>
  /** The Console's instrument cluster — passed straight through. */
  instruments?: ReactNode
}

export function WorkspaceSceneFrame({
  scene,
  scenes,
  onSelect,
  content,
  signals,
  instruments,
}: WorkspaceSceneFrameProps) {
  // Defence in depth, not a second rule: the frame still refuses to render a
  // scene this destination does not offer, so a stale prop mid-navigation can
  // never paint a House into a scheme room. It defers to the list rather than
  // re-deciding what the list should contain.
  const fallback = scenes[0] ?? 'record'
  const effectiveScene = scenes.includes(scene) ? scene : fallback
  const body = content[effectiveScene] ?? content[fallback] ?? null

  return (
    <section
      className={`workspace-scene workspace-scene-${effectiveScene}`}
      data-workspace-scene={effectiveScene}
    >
      <SceneSwitcher
        scene={effectiveScene}
        scenes={scenes}
        onSelect={onSelect}
        signals={signals}
        instruments={instruments}
      />
      <SceneMasthead scene={effectiveScene} />
      <div className="workspace-scene-content">{body}</div>
    </section>
  )
}
