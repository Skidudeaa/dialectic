import type { ReactNode } from 'react'
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
  field: 'Field',
  library: 'Library',
  ledger: 'Ledger',
  atlas: 'Atlas',
}

// One clause per place, shown under the tab row for the ACTIVE scene (and as
// a hover/focus tooltip on every tab). WHY visible and not tooltip-only: the
// names are deliberately spare, and a newcomer should not have to click every
// tab to learn the room's floor plan — hover-only meaning is also barred by
// the accessibility gate.
const SCENE_HINTS: Record<ImplementedWorkspaceScene, string> = {
  house: 'Movement across every scheme you share — each item links to its source.',
  record: 'The exact transcript — searchable, attributable, never paraphrased.',
  bench: 'The thesis under construction — causal graph, live market, open trades, what-ifs.',
  field: 'Provisional reasoning — support, tension, and synthesis candidates awaiting review.',
  library: 'What the room has actually read — filed evidence, one entry per source.',
  ledger: 'What the room holds itself to — commitments, dossier entries, memories.',
  atlas: 'The whole house mapped — rooms, artifacts, echoes, and their crossings.',
}

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
      <p className="scene-switcher-hint" aria-live="polite">{SCENE_HINTS[scene]}</p>
    </nav>
  )
}
