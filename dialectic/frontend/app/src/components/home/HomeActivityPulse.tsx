import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api.ts'
import type { HomeActivityProjection, HomeActivityRoom, RoomDestination } from '../../types/index.ts'
import './HomeActivityPulse.css'

interface HomeActivityPulseProps {
  onNavigate: (destination: RoomDestination) => Promise<boolean>
  /** Incremented after a successful member add so the displayed
   *  intersection contracts immediately instead of on the next interval. */
  refreshVersion: number
}

/**
 * Read-only cross-room pulse, rendered only in Home. Refreshes on
 * mount/Home entry, on visibility, on manual Retry, every 60 seconds
 * while visible, and when refreshVersion changes. A refresh that fails
 * AFTER a success retains the stale snapshot and says so; nothing here
 * marks source messages read, and there are no dismiss/archive/mute
 * controls — the source rooms own their own truth.
 */
export function HomeActivityPulse({ onNavigate, refreshVersion }: HomeActivityPulseProps) {
  const [snapshot, setSnapshot] = useState<HomeActivityProjection | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [collapsed, setCollapsed] = useState(false)
  const inFlightRef = useRef<Promise<void> | null>(null)

  const refresh = useCallback(() => {
    if (inFlightRef.current) return
    inFlightRef.current = api.getHomeActivity()
      .then((projection) => {
        setSnapshot(projection)
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
  }, [refresh, refreshVersion])

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') refresh()
    }
    const interval = window.setInterval(onVisible, 60_000)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refresh])

  const retry = () => {
    setLoading(snapshot === null)
    refresh()
  }

  if (loading && !snapshot) {
    return <div className="home-pulse home-pulse-note">Checking the schemes…</div>
  }

  if (error && !snapshot) {
    // First refresh failed: say so without covering transcript or composer.
    return (
      <div className="home-pulse home-pulse-note">
        Home activity unavailable — {error}
        <button className="btn btn-ghost btn-sm" onClick={retry}>Retry</button>
      </div>
    )
  }

  if (!snapshot) return null

  return (
    <div className="home-pulse">
      <div className="home-pulse-head">
        <button
          className="home-pulse-toggle"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
        >
          {collapsed ? '▸' : '▾'} Shared activity
        </button>
        {error && (
          <span className="home-pulse-stale">
            Stale — {error}
            <button className="btn btn-ghost btn-sm" onClick={retry}>Retry</button>
          </span>
        )}
      </div>
      {!collapsed && (
        <div className="home-pulse-rooms">
          {snapshot.rooms.length === 0 && (
            <p className="home-pulse-note">No shared rooms yet — every Home member must belong to a room for it to appear here.</p>
          )}
          {snapshot.rooms.map((room) => (
            <PulseRoomCard key={room.id} room={room} onNavigate={onNavigate} />
          ))}
        </div>
      )}
    </div>
  )
}

function PulseRoomCard({ room, onNavigate }: {
  room: HomeActivityRoom
  onNavigate: (destination: RoomDestination) => Promise<boolean>
}) {
  const changed = room.branches.filter((branch) => branch.unread_count > 0)
  return (
    <div className="home-pulse-card">
      <button
        className="home-pulse-room"
        onClick={() => void onNavigate({ roomId: room.id })}
      >
        <span className="home-pulse-room-name">{room.name ?? 'Untitled room'}</span>
        {room.unread_count > 0 && (
          <span className="unread-badge">{room.unread_count}</span>
        )}
      </button>
      {room.last_message_preview && (
        <p className="home-pulse-preview">
          {room.last_speaker ? `${room.last_speaker}: ` : ''}
          {room.last_message_preview}
        </p>
      )}
      {changed.length > 0 && (
        <div className="home-pulse-branches">
          {changed.map((branch) => (
            <button
              key={branch.id}
              className="home-pulse-branch"
              onClick={() => void onNavigate({ roomId: room.id, threadId: branch.id })}
            >
              ⑂ {branch.title ?? 'untitled'} ({branch.unread_count})
            </button>
          ))}
        </div>
      )}
      {room.unresolved_questions.length > 0 && (
        <p className="home-pulse-questions">
          {room.unresolved_questions.length === 1
            ? `Open question — ${room.unresolved_questions[0].speaker}: ${room.unresolved_questions[0].content_preview}`
            : `${room.unresolved_questions.length} open questions`}
        </p>
      )}
      {room.commitments_due.map((commitment) => (
        <p key={commitment.id} className="home-pulse-commitment">
          Due {new Date(commitment.deadline).toLocaleDateString()}: {commitment.claim}
        </p>
      ))}
    </div>
  )
}
