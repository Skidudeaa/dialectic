import type { ReactNode } from 'react'
import type {
  ImplementedWorkspaceScene,
} from '../../types'
import { SCENE_LABELS, SCENE_HINTS } from './sceneIdentity'
import './SceneSwitcher.css'

const PRIMARY_SCENES = new Set<ImplementedWorkspaceScene>([
  'house',
  'record',
  'bench',
  'field',
])

/** A docky-style running-dot on a scene tile: an LED plus a visible count.
 * The count is TEXT inside the button, so the signal is never color-only and
 * the accessible name reads e.g. "Record 3". */
export interface SceneSignal {
  count: number
  tone: 'red' | 'amber' | 'teal'
}

interface SceneSwitcherProps {
  scene: ImplementedWorkspaceScene
  scenes: readonly ImplementedWorkspaceScene[]
  onSelect: (scene: ImplementedWorkspaceScene) => void
  signals?: Partial<Record<ImplementedWorkspaceScene, SceneSignal>>
  /** The instrument cluster (the Console) — rendered at the tray's right. */
  instruments?: ReactNode
}

export function SceneSwitcher({ scene, scenes, onSelect, signals, instruments }: SceneSwitcherProps) {
  // A single choice is not a choice — an ordinary room shows no switcher at
  // all rather than a lone disabled-looking tab. An instrument cluster keeps
  // the tray alive even then: a record-only Home branch still gets the lamp.
  if (scenes.length < 2 && !instruments) return null
  const overflow = scenes.filter((candidate) => !PRIMARY_SCENES.has(candidate))
  const overflowActive = overflow.includes(scene)

  return (
    <nav className="scene-switcher-wrap" aria-label="Room views">
      <div className="scene-switcher">
        {scenes.map((candidate) => (
          <button
            key={candidate}
            type="button"
            className={`scene-switcher-action scene-switcher-${PRIMARY_SCENES.has(candidate) ? 'primary' : 'secondary'}${candidate === scene ? ' is-active' : ''}`}
            aria-current={candidate === scene ? 'page' : undefined}
            title={SCENE_HINTS[candidate]}
            onClick={() => {
              // Selecting the active scene must not push a duplicate history
              // entry; Back would then need two presses to leave the scene.
              if (candidate !== scene) onSelect(candidate)
            }}
          >
            {SCENE_LABELS[candidate]}
            {(signals?.[candidate]?.count ?? 0) > 0 && (
              <span className={`scene-signal scene-signal-${signals![candidate]!.tone}`}>
                <span className="scene-signal-led" aria-hidden="true" />
                {signals![candidate]!.count}
              </span>
            )}
          </button>
        ))}
        {overflow.length > 0 && (
          <details className="scene-switcher-more">
            <summary aria-current={overflowActive ? 'page' : undefined}>
              {overflowActive ? `More views · ${SCENE_LABELS[scene]}` : 'More views'}
            </summary>
            <div className="scene-switcher-menu" role="menu" aria-label="More room views">
              {overflow.map((candidate) => (
                <button
                  key={candidate}
                  type="button"
                  role="menuitem"
                  aria-current={candidate === scene ? 'page' : undefined}
                  onClick={() => {
                    if (candidate !== scene) onSelect(candidate)
                  }}
                >
                  {SCENE_LABELS[candidate]}
                </button>
              ))}
            </div>
          </details>
        )}
        {instruments}
      </div>
    </nav>
  )
}
