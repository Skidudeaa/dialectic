import type { ReactNode } from 'react'
import type { ImplementedWorkspaceScene } from '../../types'
import { SceneSwitcher } from './SceneSwitcher'
import './WorkspaceSceneFrame.css'

interface WorkspaceSceneFrameProps {
  scene: ImplementedWorkspaceScene
  isHomeRoot: boolean
  onSelect: (scene: ImplementedWorkspaceScene) => void
  house: ReactNode
  record: ReactNode
}

export function WorkspaceSceneFrame({
  scene,
  isHomeRoot,
  onSelect,
  house,
  record,
}: WorkspaceSceneFrameProps) {
  // Only Home's root has a household to show. Everywhere else the frame forces
  // Record rather than trusting the caller, so a stale `scene` prop can never
  // render an empty House in a scheme room.
  const scenes: readonly ImplementedWorkspaceScene[] = isHomeRoot
    ? ['house', 'record']
    : ['record']
  const effectiveScene: ImplementedWorkspaceScene = isHomeRoot
    ? scene
    : 'record'

  return (
    <section
      className={`workspace-scene workspace-scene-${effectiveScene}`}
      data-workspace-scene={effectiveScene}
    >
      <SceneSwitcher
        scene={effectiveScene}
        scenes={scenes}
        onSelect={onSelect}
      />
      <div className="workspace-scene-content">
        {effectiveScene === 'house' ? house : record}
      </div>
    </section>
  )
}
