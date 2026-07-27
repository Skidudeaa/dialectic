import './ParticipantsBar.css'

interface Participant {
  id: string
  name: string
  isOnline: boolean
  isClaude?: boolean
  status?: string
  /** Last presence heartbeat, used to say how long ago someone was here. */
  lastSeen?: string | null
}

interface ParticipantsBarProps {
  participants: Participant[]
}

/**
 * "3h ago" rather than a timestamp. In a two-person room the useful question is
 * how stale the other person's attention is, not the wall-clock moment.
 */
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

export function ParticipantsBar({ participants }: ParticipantsBarProps) {
  return (
    <div className="participants-bar">
      {participants.map(p => {
        const status = p.status ?? (p.isOnline ? 'online' : 'offline')
        // Claude is always present, and an "away" label for it would be noise.
        const ago = p.isClaude || p.isOnline ? null : agoLabel(p.lastSeen)
        return (
          <div
            key={p.id}
            className={`participant-chip ${p.isClaude ? 'is-claude' : ''}`}
            title={p.isClaude ? 'Claude' : `${p.name} — ${status}${ago ? `, last seen ${ago}` : ''}`}
          >
            <span className={`presence-dot ${status === 'online' ? 'online' : status === 'away' ? 'away' : 'offline'}`} />
            <span className="p-name">{p.name}</span>
            {ago && <span className="p-last-seen">{ago}</span>}
          </div>
        )
      })}
    </div>
  )
}
