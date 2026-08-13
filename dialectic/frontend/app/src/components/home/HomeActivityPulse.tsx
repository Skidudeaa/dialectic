import { useCallback, useEffect, useRef, useState } from 'react'
import { HouseMovement } from './HouseMovement'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import { api } from '../../lib/api.ts'
import type { HomeActivityProjection, HomeActivityRoom, RoomDestination } from '../../types/index.ts'
import './HomeActivityPulse.css'

export interface HomeResident {
  id: string
  name: string
  isOnline: boolean
  isClaude?: boolean
  status?: string
  lastSeen?: string | null
}

interface HomeActivityPulseProps {
  onNavigate: (destination: RoomDestination) => Promise<boolean>
  /** Incremented after a successful member add so the displayed
   *  intersection contracts immediately instead of on the next interval. */
  refreshVersion: number
  residents: HomeResident[]
}

type Need =
  | { kind: 'due'; room: HomeActivityRoom; claim: string; deadline: string; sort: number }
  | { kind: 'question'; room: HomeActivityRoom; speaker: string; preview: string; threadId: string; sort: number }
  | { kind: 'unread'; room: HomeActivityRoom; sort: number }

/**
 * The house: who is here, what needs a body, and doors into the schemes.
 * Same projection as before — read-only, membership-fenced, no receipts
 * written. The transcript under this is the table, not the place.
 */
export function HomeActivityPulse({ onNavigate, refreshVersion, residents }: HomeActivityPulseProps) {
  const [snapshot, setSnapshot] = useState<HomeActivityProjection | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
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
    return <div className="home-house home-house-note">Checking the house…</div>
  }

  if (error && !snapshot) {
    return (
      <div className="home-house home-house-note">
        Home activity unavailable — {error}
        <button className="btn btn-ghost btn-sm" onClick={retry}>Retry</button>
      </div>
    )
  }

  if (!snapshot) return null

  const needs = collectNeeds(snapshot.rooms)

  return (
    <div className="home-house">
      <div className="home-lintel">
        <div className="home-residents">
          {residents.map((resident) => {
            const status = resident.status ?? (resident.isOnline ? 'online' : 'offline')
            const ago = resident.isClaude || resident.isOnline ? null : agoLabel(resident.lastSeen)
            return (
              <span
                key={resident.id}
                className={`home-resident${resident.isClaude ? ' is-claude' : ''}`}
                title={resident.isClaude ? `${PARTICIPANT_NAME} lives here` : `${resident.name} — ${status}${ago ? `, last seen ${ago}` : ''}`}
              >
                <span className={`presence-dot ${status === 'online' ? 'online' : status === 'away' ? 'away' : 'offline'}`} />
                <span className="home-resident-name">{resident.name}</span>
                {ago && <span className="home-resident-ago">{ago}</span>}
              </span>
            )
          })}
        </div>
        {error && (
          <span className="home-house-stale">
            Stale — {error}
            <button className="btn btn-ghost btn-sm" onClick={retry}>Retry</button>
          </span>
        )}
      </div>

      {needs.length > 0 && (
        <section className="home-needs" aria-label="Needs you">
          <h2>Needs you</h2>
          <div className="home-needs-list">
            {needs.map((need) => (
              <NeedRow key={needKey(need)} need={need} onNavigate={onNavigate} />
            ))}
          </div>
        </section>
      )}

      <HouseMovement
        movement={snapshot.rooms.flatMap((room) => room.movement ?? [])}
        onNavigate={onNavigate}
      />

      <section className="home-wings" aria-label="The house">
        <h2>The house</h2>
        {snapshot.rooms.length === 0 ? (
          <p className="home-house-empty">No shared rooms yet — every Home member must belong to a room for it to appear here.</p>
        ) : (
          <div className="home-doors">
            {snapshot.rooms.map((room) => (
              <SchemeDoor key={room.id} room={room} onNavigate={onNavigate} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function NeedRow({ need, onNavigate }: {
  need: Need
  onNavigate: (destination: RoomDestination) => Promise<boolean>
}) {
  switch (need.kind) {
    case 'due':
      return (
        <button
          className="home-need due"
          onClick={() => void onNavigate({ roomId: need.room.id })}
        >
          <span className="home-need-kicker">Due {formatDay(need.deadline)}</span>
          <span className="home-need-room">{schemeName(need.room.name)}</span>
          <span className="home-need-body">{need.claim}</span>
        </button>
      )
    case 'question':
      return (
        <button
          className="home-need question"
          onClick={() => void onNavigate({ roomId: need.room.id, threadId: need.threadId })}
        >
          <span className="home-need-kicker">{need.speaker} asked</span>
          <span className="home-need-room">{schemeName(need.room.name)}</span>
          <span className="home-need-body">{need.preview}</span>
        </button>
      )
    case 'unread':
      return (
        <button
          className="home-need unread"
          onClick={() => void onNavigate({ roomId: need.room.id })}
        >
          <span className="home-need-kicker">{need.room.unread_count} unread</span>
          <span className="home-need-room">{schemeName(need.room.name)}</span>
          <span className="home-need-body">{doorBody(need.room)}</span>
        </button>
      )
    default: {
      const _exhaustive: never = need
      return _exhaustive
    }
  }
}

function SchemeDoor({ room, onNavigate }: {
  room: HomeActivityRoom
  onNavigate: (destination: RoomDestination) => Promise<boolean>
}) {
  const changed = room.branches.filter((branch) => branch.unread_count > 0)
  const unread = room.unread_count > 0
  return (
    <div className={`home-door${unread ? ' unread' : ''}`}>
      <button
        className="home-door-open"
        onClick={() => void onNavigate({ roomId: room.id })}
      >
        <span className="home-door-name">{schemeName(room.name)}</span>
        {unread && <span className="unread-badge">{room.unread_count}</span>}
      </button>
      <p className="home-door-kicker">{doorKicker(room)}</p>
      {doorBody(room) && <p className="home-door-body">{doorBody(room)}</p>}
      {changed.length > 0 && (
        <div className="home-door-branches">
          {changed.map((branch) => (
            <button
              key={branch.id}
              className="home-door-branch"
              onClick={() => void onNavigate({ roomId: room.id, threadId: branch.id })}
            >
              ⑂ {branch.title ?? 'untitled'} ({branch.unread_count})
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function collectNeeds(rooms: HomeActivityRoom[]): Need[] {
  const items: Need[] = []
  for (const room of rooms) {
    for (const commitment of room.commitments_due) {
      items.push({
        kind: 'due',
        room,
        claim: commitment.claim,
        deadline: commitment.deadline,
        sort: new Date(commitment.deadline).getTime(),
      })
    }
    for (const question of room.unresolved_questions) {
      items.push({
        kind: 'question',
        room,
        speaker: displaySpeaker(question.speaker),
        preview: oneLinePreview(question.content_preview),
        threadId: question.thread_id,
        sort: -new Date(question.timestamp).getTime(),
      })
    }
    if (room.unread_count > 0 && room.unresolved_questions.length === 0 && room.commitments_due.length === 0) {
      items.push({
        kind: 'unread',
        room,
        sort: -new Date(room.last_message_at ?? 0).getTime(),
      })
    }
  }
  items.sort((a, b) => {
    const rank = (need: Need) => (need.kind === 'due' ? 0 : need.kind === 'question' ? 1 : 2)
    const byKind = rank(a) - rank(b)
    return byKind !== 0 ? byKind : a.sort - b.sort
  })
  return items.slice(0, 6)
}

function needKey(need: Need): string {
  switch (need.kind) {
    case 'due':
      return `due:${need.room.id}:${need.deadline}:${need.claim}`
    case 'question':
      return `q:${need.threadId}:${need.preview}`
    case 'unread':
      return `u:${need.room.id}`
    default: {
      const _exhaustive: never = need
      return _exhaustive
    }
  }
}

function schemeName(name: string | null): string {
  if (!name) return 'Untitled'
  return name.replace(/\s+Trading Room$/i, '').replace(/\s+Trading$/i, '')
}

function isOvernightDump(preview: string | null, speaker: string | null): boolean {
  const text = (preview ?? '').toLowerCase()
  const who = (speaker ?? '').toLowerCase()
  return who.includes('annotator')
    || text.includes('morning brief')
    || text.includes('conversation summary')
}

function doorKicker(room: HomeActivityRoom): string {
  const due = room.commitments_due[0]
  if (due) return `Due ${formatDay(due.deadline)}`
  if (room.unresolved_questions.length === 1) {
    return `${displaySpeaker(room.unresolved_questions[0].speaker)} asked`
  }
  if (room.unresolved_questions.length > 1) {
    return `${room.unresolved_questions.length} open questions`
  }
  if (isOvernightDump(room.last_message_preview, room.last_speaker)) {
    return room.unread_count > 0 ? 'Overnight brief' : 'Overnight'
  }
  const speaker = displaySpeaker(room.last_speaker)
  const ago = agoLabel(room.last_message_at)
  if (speaker && ago) return `${speaker} · ${ago}`
  if (speaker) return speaker
  if (ago) return ago
  return 'Quiet'
}

function doorBody(room: HomeActivityRoom): string {
  const due = room.commitments_due[0]
  if (due) return due.claim
  const question = room.unresolved_questions[0]
  if (question) return oneLinePreview(question.content_preview)
  if (isOvernightDump(room.last_message_preview, room.last_speaker)) return ''
  return oneLinePreview(room.last_message_preview)
}

function displaySpeaker(raw: string | null | undefined): string {
  if (!raw) return ''
  if (raw === 'llm_primary' || raw === 'llm_provoker' || raw === 'llm_annotator') return PARTICIPANT_NAME
  if (raw === 'system') return 'System'
  return raw
}

function oneLinePreview(raw: string | null | undefined): string {
  if (!raw) return ''
  return raw
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#*_`>~]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 110)
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

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
