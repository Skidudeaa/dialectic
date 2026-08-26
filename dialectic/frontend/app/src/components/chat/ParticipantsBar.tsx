import './ParticipantsBar.css'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import { agoLabel } from '../../lib/relativeTime.ts'

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
            title={p.isClaude ? PARTICIPANT_NAME : `${p.name} — ${status}${ago ? `, last seen ${ago}` : ''}`}
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
