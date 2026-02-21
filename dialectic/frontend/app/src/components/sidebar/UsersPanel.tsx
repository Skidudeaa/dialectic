import './UsersPanel.css'

interface UsersPanelProps {
  users: { id: string; name: string; status: string }[]
}

export function UsersPanel({ users }: UsersPanelProps) {
  return (
    <div className="users-list">
      {users.map(u => (
        <div key={u.id} className="user-list-item">
          <span className={`user-list-dot ${u.status}`} />
          <span className="user-list-name">{u.name}</span>
          <span className="user-list-status">{u.status}</span>
        </div>
      ))}
      {users.length === 0 && (
        <div style={{ color: 'var(--text-ghost)', fontSize: '0.8rem', padding: '1rem', textAlign: 'center' }}>
          No users in this room
        </div>
      )}
    </div>
  )
}
