import { useEffect, useState } from 'react'
import { api, type RoundMove } from '../../lib/api.ts'
import type { RoomDestination } from '../../types'
import './YourMove.css'

/**
 * "Dan moved on Brent. Your move." — the first thing Home shows.
 *
 * WHY (2026-09-02): the Round fired on schedule for weeks and its payoff never
 * triggered once, because nothing told either human it was their turn. This
 * reads the open questions across the viewer's rooms and puts the ones a peer
 * has answered, and the viewer has not, on top. Names only; the blindness rule
 * is enforced server-side and this shows no probability.
 */
export function YourMove({ onNavigate, refreshVersion = 0 }: {
  onNavigate: (destination: RoomDestination) => Promise<boolean> | void
  refreshVersion?: number
}) {
  const [moves, setMoves] = useState<RoundMove[] | null>(null)

  useEffect(() => {
    let live = true
    api.getRoundMoves().then((r) => { if (live) setMoves(r.moves) }).catch(() => { if (live) setMoves([]) })
    return () => { live = false }
  }, [refreshVersion])

  if (moves === null) return null
  const pending = moves.filter((m) => !m.mine)
  const done = moves.filter((m) => m.mine)

  return (
    <section className="your-move" aria-label="Your move">
      <div className="your-move-head">
        <b>{pending.length ? `Your move · ${pending.length}` : 'No open question waits on you'}</b>
        <span>{moves.length} open in the Round</span>
      </div>
      {moves.length > 0 && (
        <ul className="your-move-list">
          {[...pending, ...done].map((m) => (
            <li key={m.commitment_id}>
              <button
                type="button"
                className={`your-move-item ${m.mine ? 'done' : ''}`}
                onClick={() => void onNavigate({ roomId: m.room_id, threadId: m.thread_id, messageId: m.message_id ?? undefined })}
              >
                <span className="your-move-claim">{m.claim}</span>
                <span className="your-move-meta">
                  {m.mine
                    ? <>you forecast · {m.peers_moved.length ? `${m.peers_moved.join(', ')} too` : 'waiting on the other'}</>
                    : m.peers_moved.length
                      ? <><b>{m.peers_moved.join(', ')} moved</b> · {m.room_name}</>
                      : <>{m.room_name} · nobody yet</>}
                  {m.closes ? ` · closes ${m.closes}` : ''}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {moves.length === 0 && <div className="your-move-quiet">The next question lands at 09:00. One a day, one room at a time.</div>}
    </section>
  )
}
