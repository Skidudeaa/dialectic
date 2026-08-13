import type { WorkspaceObject } from '../../../types/workspace.ts'
import type { WorkspaceObjectsState } from '../../../hooks/useWorkspaceObjects.ts'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'
import { SceneEmpty, SceneLoading, SceneUnavailable } from '../SceneEmpty'
import { WorkspaceObjectList } from '../WorkspaceObjectList'

/**
 * The Library — the room's durable evidence (design v2 §7.6).
 *
 * A reading and its `reading:<domain>-<slug>` memory twin are ONE object here.
 * That is not this component's doing: `workspace_objects.py` folds the twin in
 * through the writer's own key function, and the dossier statement excludes the
 * whole namespace in SQL. Both guards are mutation-tested on the backend. This
 * surface simply must not undo it — which is why it filters on `kind` and never
 * merges or de-duplicates anything itself.
 */
export function LibraryScene({
  state,
  onOpen,
}: {
  state: WorkspaceObjectsState
  onOpen?: (object: WorkspaceObject) => void
}) {
  if (state.status === 'loading') return <SceneLoading kicker="Library" />
  if (state.status === 'unavailable') {
    return (
      <SceneUnavailable
        kicker="Library"
        what="the library"
        error={state.error}
        onRetry={state.retry}
      />
    )
  }

  const readings = state.objects.filter((o) => o.kind === 'reading')

  if (readings.length === 0) {
    return (
      <SceneEmpty kicker="Library" headline="Nothing filed here yet.">
        <p>
          The Library holds the sources this room has actually kept — the
          article behind a claim, with where it came from and why it mattered.
        </p>
        <p>
          Two ways in: paste a link in the conversation and{' '}
          {PARTICIPANT_NAME} reads it and offers to file it, or it files one
          itself when it finds
          something that bears on this room&rsquo;s thesis. Either way{' '}
          <strong>your Accept is what files it</strong> — nothing lands here on
          its own.
        </p>
      </SceneEmpty>
    )
  }

  return (
    <div className="scene-body">
      <WorkspaceObjectList objects={readings} onOpen={onOpen} label="Filed readings" />
    </div>
  )
}
