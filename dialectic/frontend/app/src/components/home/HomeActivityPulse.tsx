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
 * Read-only scheme board, rendered only in Home. This is the place —
 * doors into shared work — not a chat widget. Refreshes on mount/Home
 * entry, on visibility, on manual Retry, every 60 seconds while visible,
 * and when refreshVersion changes. A refresh that fails AFTER a success
 * retains the stale snapshot and says so; nothing here marks source
 * messages read, and there are no dismiss/archive/mute controls.
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

  const unreadRooms = snapshot.rooms.filter((room) => room.unread_count > 0).length

  return (
    <div className="home-pulse">
      <div className="home-pulse-head">
        <button
          className="home-pulse-toggle"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
        >
          {collapsed ? '▸' : '▾'} What&rsquo;s moving
        </button>
        {unreadRooms > 0 && (
          <span className="home-pulse-count">
            {unreadRooms} unread
          </span>
        )}
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
            <p className="home-pulse-empty">No shared rooms yet — every Home member must belong to a room for it to appear here.</p>
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
  const preview = oneLinePreview(room.last_message_preview)
  const speaker = displaySpeaker(room.last_speaker)
  const ago = agoLabel(room.last_message_at)
  const unread = room.unread_count > 0
  return (
    <div className={`home-pulse-card${unread ? ' unread' : ''}`}>
      <button
        className="home-pulse-room"
        onClick={() => void onNavigate({ roomId: room.id })}
      >
        <span className="home-pulse-room-name">{room.name ?? 'Untitled room'}</span>
        {unread && (
          <span className="unread-badge">{room.unread_count}</span>
        )}
      </button>
      {(speaker || ago) && (
        <p className="home-pulse-meta">
          {speaker}{speaker && ago ? ' · ' : ''}{ago}
        </p>
      )}
      {preview && (
        <p className="home-pulse-preview">{preview}</p>
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
            ? `Open question — ${displaySpeaker(room.unresolved_questions[0].speaker)}: ${oneLinePreview(room.unresolved_questions[0].content_preview)}`
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

/** LLM rows store speaker_type when there is no display name. */
function displaySpeaker(raw: string | null | undefined): string {
  if (!raw) return ''
  if (raw === 'llm_primary' || raw === 'llm_provoker' || raw === 'llm_annotator') return 'Claude'
  if (raw === 'system') return 'System'
  return raw
}

/** Morning briefs arrive as markdown; the board wants one spoken line. */
function oneLinePreview(raw: string | null | undefined): string {
  if (!raw) return ''
  return raw
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#*_`>~]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 96)
}

function agoLabel(iso: string | null | undefined): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  const minutes = Math.floor((Date.now() - then) / 60000)
  if (minutes < 0) return null
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return days < 7 ? `${days}d ago` : 'a while ago'
}
