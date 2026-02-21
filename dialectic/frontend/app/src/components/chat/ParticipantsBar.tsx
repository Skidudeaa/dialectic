import './ParticipantsBar.css'

interface Participant {
  id: string
  name: string
  isOnline: boolean
  isClaude?: boolean
}

interface ParticipantsBarProps {
  participants: Participant[]
}

export function ParticipantsBar({ participants }: ParticipantsBarProps) {
  return (
    <div className="participants-bar">
      {participants.map(p => (
        <div key={p.id} className={`participant-chip ${p.isClaude ? 'is-claude' : ''}`}>
          <span className={`presence-dot ${p.isOnline ? 'online' : 'offline'}`} />
          <span className="p-name">{p.name}</span>
        </div>
      ))}
    </div>
  )
}
