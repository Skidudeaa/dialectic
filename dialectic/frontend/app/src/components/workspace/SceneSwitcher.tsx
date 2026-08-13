import type {
  ImplementedWorkspaceScene,
} from '../../types'
import './SceneSwitcher.css'

// A total Record over the union on purpose: adding a scene to
// IMPLEMENTED_WORKSPACE_SCENES without naming it here is a build error, not a
// blank tab discovered in the browser.
//
// The names are places, not features — the room is a workroom and these are
// parts of it. "Library" says what it holds; "Evidence Management" would not.
const SCENE_LABELS: Record<ImplementedWorkspaceScene, string> = {
  house: 'House',
  record: 'Record',
  bench: 'Bench',
  library: 'Library',
  ledger: 'Ledger',
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
