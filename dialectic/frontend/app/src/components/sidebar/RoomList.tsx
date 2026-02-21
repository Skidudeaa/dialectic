import type { UserRoom } from '../../types'
import './RoomList.css'

interface RoomListProps {
  rooms: UserRoom[]
  activeRoomId: string | null
  onRoomSelect: (roomId: string) => void
  onCreateRoom: () => void
  userName: string
  onLogout: () => void
}

export function RoomList({ rooms, activeRoomId, onRoomSelect, onCreateRoom, userName, onLogout }: RoomListProps) {
  return (
    <>
      <div className="sidebar-rooms-header">
        <h2>Rooms</h2>
        <button className="btn btn-ghost btn-sm" onClick={onCreateRoom} title="Create Room">+</button>
      </div>
      <div className="room-list">
        {rooms.length === 0 ? (
          <div className="empty-state" style={{ padding: '1.5rem', fontSize: '0.78rem' }}>No rooms yet</div>
        ) : (
          rooms.map(room => (
            <div
              key={room.id}
              className={`room-item ${room.id === activeRoomId ? 'active' : ''}`}
              onClick={() => onRoomSelect(room.id)}
            >
              <div className="room-item-name">{room.name ?? `Room ${room.id.slice(0, 6)}`}</div>
              {room.last_message_preview && (
                <div className="room-item-preview">{room.last_message_preview}</div>
              )}
              {room.unread_count > 0 && (
                <span className="unread-badge">{room.unread_count}</span>
              )}
            </div>
          ))
        )}
      </div>
      <div className="sidebar-rooms-footer">
        <div className="user-info-bar">
          <div className="avatar avatar-self">{userName.charAt(0).toUpperCase()}</div>
          <span className="user-info-name">{userName}</span>
          <button className="btn btn-ghost btn-sm" onClick={onLogout} title="Log out">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/>
              <polyline points="16 17 21 12 16 7"/>
              <line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
          </button>
        </div>
      </div>
    </>
  )
}
