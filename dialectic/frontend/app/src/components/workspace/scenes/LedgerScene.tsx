import type { ReactNode } from 'react'
import type { WorkspaceObject } from '../../../types/workspace.ts'
import type { WorkspaceObjectsState } from '../../../hooks/useWorkspaceObjects.ts'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'
import { SceneEmpty, SceneLoading, SceneUnavailable } from '../SceneEmpty'
import { WorkspaceObjectList } from '../WorkspaceObjectList'

/**
 * The Ledger — what this room has agreed, and how it is remembered (§7.7).
 *
 * The Ledger holds state the room has authorized; the Dossier is how remembered
 * material is presented. They are kept as two labelled groups rather than one
 * list because §7.7 requires the meanings stay distinct — and in particular
 * because a PERSONAL recall promotion is not a Ledger promotion. Blurring those
 * is how a private grant would start reading as shared house state.
 *
 * `dossier` carries the largest population in production (425 active memories
 * across 8 rooms), which is why this scene was built before the emptier ones.
 */
export function LedgerScene({
  state,
  onOpen,
  memoryPanel,
}: {
  state: WorkspaceObjectsState
  onOpen?: (object: WorkspaceObject) => void
  /** The existing MemoryPanel, recomposed rather than rebuilt (§19.5). */
  memoryPanel?: ReactNode
}) {
  if (state.status === 'loading') return <SceneLoading kicker="Ledger" />
  if (state.status === 'unavailable') {
    return (
      <SceneUnavailable
        kicker="Ledger"
        what="the ledger"
        error={state.error}
        onRetry={state.retry}
      />
    )
  }

  const entries = state.objects.filter((o) => o.kind === 'dossier_entry')

  if (entries.length === 0) {
    return (
      <SceneEmpty kicker="Ledger" headline="This room has not agreed anything yet.">
        <p>
          The Ledger is what the room takes as settled — decisions, definitions,
          the premises an argument can lean on without re-litigating them.
        </p>
        <p>
          Facts land here when you save one, or when {PARTICIPANT_NAME} records
          something it heard. Restate a fact later and the new version{' '}
          <strong>supersedes</strong> the old one rather than sitting beside it,
          and the old one keeps its history.
        </p>
        {memoryPanel}
      </SceneEmpty>
    )
  }

  return (
    <div className="scene-body">
      <WorkspaceObjectList objects={entries} onOpen={onOpen} label="What this room holds" />
      {memoryPanel}
    </div>
  )
}
