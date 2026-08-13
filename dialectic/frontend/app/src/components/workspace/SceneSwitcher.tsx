import type {
  ImplementedWorkspaceScene,
} from '../../types'
import './SceneSwitcher.css'

const SCENE_LABELS: Record<ImplementedWorkspaceScene, string> = {
  house: 'House',
  record: 'Record',
}

interface SceneSwitcherProps {
  scene: ImplementedWorkspaceScene
  scenes: readonly ImplementedWorkspaceScene[]
  onSelect: (scene: ImplementedWorkspaceScene) => void
}

export function SceneSwitcher({ scene, scenes, onSelect }: SceneSwitcherProps) {
  // A single choice is not a choice — an ordinary room shows no switcher at all
  // rather than a lone disabled-looking tab.
  if (scenes.length < 2) return null

  return (
    <nav className="scene-switcher" aria-label="Room views">
      {scenes.map((candidate) => (
        <button
          key={candidate}
          type="button"
          className={`scene-switcher-action${candidate === scene ? ' is-active' : ''}`}
          aria-current={candidate === scene ? 'page' : undefined}
          onClick={() => {
            // Selecting the active scene must not push a duplicate history
            // entry; Back would then need two presses to leave the scene.
            if (candidate !== scene) onSelect(candidate)
          }}
        >
          {SCENE_LABELS[candidate]}
        </button>
      ))}
    </nav>
  )
}
