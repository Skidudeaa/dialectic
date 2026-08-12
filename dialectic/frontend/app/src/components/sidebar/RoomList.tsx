import type { ThreadNode, UserRoom } from '../../types'
import { BranchTree } from './BranchTree'
import './RoomList.css'

interface RoomListProps {
  rooms: UserRoom[]
  activeRoomId: string | null
  onRoomSelect: (roomId: string) => void
  onCreateRoom: () => void
  userName: string
  onLogout: () => void
  /** The active room's fork tree — rendered compact beneath its card. */
  genealogy: ThreadNode[]
  activeThreadId: string | null
  onThreadSelect: (threadId: string) => void
}

/**
 * The room rail — and, unchanged, the content of the shipped mobile
 * navigation drawer. Home is a place-pin above Rooms, not a case card;
 * ordinary rooms keep unread badges and previews; only the active room
 * expands its branch genealogy.
 */
export function RoomList({
  rooms,
  activeRoomId,
  onRoomSelect,
  onCreateRoom,
  userName,
  onLogout,
  genealogy,
  activeThreadId,
  onThreadSelect,
}: RoomListProps) {
  const home = rooms.find((room) => room.is_home)
  const ordinary = rooms.filter((room) => !room.is_home)
  const homeActive = home != null && home.id === activeRoomId

  const renderRoom = (room: UserRoom) => (
    <div key={room.id}>
      <div
        className={`room-item ${room.id === activeRoomId ? 'active' : ''}`}
        onClick={() => onRoomSelect(room.id)}
      >
        <div className="room-item-name">
          {room.name ?? `Room ${room.id.slice(0, 6)}`}
        </div>
        {room.last_message_preview && (
          <div className="room-item-preview">{room.last_message_preview}</div>
        )}
        {room.unread_count > 0 && (
          <span className="unread-badge">{room.unread_count}</span>
        )}
      </div>
      {room.id === activeRoomId && (
        <BranchTree
          compact
          nodes={genealogy}
          activeThreadId={activeThreadId}
          onSelect={onThreadSelect}
        />
      )}
    </div>
  )

  return (
    <>
      {home && (
        <div className="home-pin-wrap">
          <button
            type="button"
            className={`home-pin${homeActive ? ' active' : ''}`}
            onClick={() => onRoomSelect(home.id)}
            aria-current={homeActive ? 'page' : undefined}
            aria-label="Home"
          >
            <svg className="home-pin-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
              <polyline points="9 22 9 12 15 12 15 22"/>
            </svg>
            <span className="home-pin-label">Home</span>
            {home.unread_count > 0 && (
              <span className="unread-badge">{home.unread_count}</span>
            )}
          </button>
          {homeActive && (
            <BranchTree
              compact
              nodes={genealogy}
              activeThreadId={activeThreadId}
              onSelect={onThreadSelect}
            />
          )}
        </div>
      )}
      <div className="sidebar-rooms-header">
        <h2>Rooms</h2>
        <button className="btn btn-ghost btn-sm" onClick={onCreateRoom} title="Create Room">+</button>
      </div>
      <div className="room-list">
        {ordinary.length === 0 ? (
          <div className="empty-state" style={{ padding: '1.5rem', fontSize: '0.78rem' }}>No rooms yet</div>
        ) : (
          ordinary.map(renderRoom)
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
