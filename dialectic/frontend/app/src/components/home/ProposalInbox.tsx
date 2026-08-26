import { useCallback, useEffect, useRef, useState } from 'react'
import { agoLabel } from '../../lib/relativeTime.ts'
import { api } from '../../lib/api.ts'
import type { HomeProposalItem, RoomDestination } from '../../types/index.ts'
import type { ProposalKind } from '../../types/workspace.ts'
import './ProposalInbox.css'

const KIND_LABELS: Partial<Record<ProposalKind, string>> = {
  prediction_draft: 'Prediction',
  thesis_proposal: 'Thesis',
  thesis_draft: 'Thesis',
  commitment_proposal: 'Commitment',
  reading_draft: 'Reading',
  prediction_resolution: 'Resolution',
  trade_proposal: 'Trade',
}

/** A kind this build has never seen still renders — humanized, not blank —
 *  rather than the inbox breaking on the next proposal type the room adds. */
function kindLabel(kind: string): string {
  return KIND_LABELS[kind as ProposalKind] ?? kind.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

interface ProposalInboxProps {
  onNavigate: (destination: RoomDestination) => Promise<boolean> | void
}

/**
 * The human-action inbox for proposals (design audit H03): every prediction,
 * thesis, reading, commitment and resolution proposed anywhere in the house,
 * in one place, instead of scroll-back archaeology room by room.
 *
 * Own fetch/loading/error, matching HomeActivityPulse's stale-data-with-retry
 * model (H06) — a failed refresh keeps showing the last good list rather than
 * blanking it.
 */
export function ProposalInbox({ onNavigate }: ProposalInboxProps) {
  const [proposals, setProposals] = useState<HomeProposalItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const inFlightRef = useRef<Promise<void> | null>(null)

  const refresh = useCallback(() => {
    if (inFlightRef.current) return
    inFlightRef.current = api.getHomeProposals()
      .then((res) => {
        setProposals(res.proposals)
        setError(null)
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Refresh failed')
      })
      .finally(() => {
        inFlightRef.current = null
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const retry = () => {
    setLoading(proposals === null)
    refresh()
  }

  if (loading && proposals === null) {
    return <div className="proposal-inbox proposal-inbox-note">Checking proposals…</div>
  }

  if (error && proposals === null) {
    return (
      <div className="proposal-inbox proposal-inbox-note">
        Proposals unavailable — {error}
        <button className="btn btn-ghost btn-sm" onClick={retry}>Retry</button>
      </div>
    )
  }

  if (proposals === null) return null

  // 'proposed' is the one status that still needs a human; every other
  // status in the vocabulary (accepted/dismissed/superseded/expired/failed)
  // is a settled outcome, never re-hidden — just demoted behind the fold.
  const pending = proposals
    .filter((p) => p.status === 'proposed')
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  const resolved = proposals
    .filter((p) => p.status !== 'proposed')
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))

  return (
    <section className="proposal-inbox" aria-label="Proposals">
      <div className="proposal-inbox-head">
        <h2>Proposals</h2>
        {error && (
          <span className="proposal-inbox-stale">
            Stale — {error}
            <button className="btn btn-ghost btn-sm" onClick={retry}>Retry</button>
          </span>
        )}
      </div>

      {proposals.length === 0 ? (
        <p className="proposal-inbox-empty">Nothing pending — no open proposals right now.</p>
      ) : (
        <>
          {pending.length === 0 ? (
            <p className="proposal-inbox-empty">Nothing needs a decision right now.</p>
          ) : (
            <div className="proposal-inbox-list">
              {pending.map((item) => (
                <ProposalRow key={item.id} item={item} onNavigate={onNavigate} />
              ))}
            </div>
          )}

          {resolved.length > 0 && (
            <details className="proposal-inbox-fold">
              <summary>
                Resolved
                <span className="proposal-inbox-fold-count">{resolved.length}</span>
              </summary>
              <div className="proposal-inbox-fold-body">
                {resolved.map((item) => (
                  <ProposalRow key={item.id} item={item} onNavigate={onNavigate} />
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </section>
  )
}

function ProposalRow({ item, onNavigate }: {
  item: HomeProposalItem
  onNavigate: (destination: RoomDestination) => Promise<boolean> | void
}) {
  const ago = agoLabel(item.created_at)
  return (
    <button
      type="button"
      className={`proposal-item is-${item.status}`}
      onClick={() => {
        void onNavigate({
          roomId: item.room_id,
          threadId: item.branch_id,
          messageId: item.source_message_id,
        })
      }}
    >
      <span className="proposal-item-top">
        <span className="proposal-item-kind">{kindLabel(item.proposal_kind)}</span>
        <span className={`proposal-status-chip is-${item.status}`}>{item.status}</span>
        {ago && <span className="proposal-item-time">{ago}</span>}
      </span>
      <span className="proposal-item-detail">
        <span className="proposal-item-room">{item.room_name || 'Untitled'}</span>
        <span className="proposal-item-rationale">{item.rationale}</span>
      </span>
    </button>
  )
}
