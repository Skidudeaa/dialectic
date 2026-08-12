import { useState } from 'react'
import { useAppStore } from '../../stores/appStore.ts'
import { api } from '../../lib/api.ts'
import type { Room, RoomDestination, UserRoom } from '../../types/index.ts'
import './RoomAccess.css'

const INVITE_PREFIX = 'dialectic-v1:'

function parseInviteCode(value: string): { roomId: string; token: string } | null {
  const trimmed = value.trim()
  if (!trimmed.startsWith(INVITE_PREFIX)) return null

  const [version, roomId, token, ...extra] = trimmed.split(':')
  if (version !== 'dialectic-v1' || !roomId || !token || extra.length > 0) return null

  return { roomId, token }
}

interface RoomAccessProps {
  mode: 'screen' | 'dialog'
  rooms: UserRoom[]
  onRoomSelect: (destination: RoomDestination) => Promise<boolean>
  onRoomGranted: (
    room: Pick<UserRoom, 'id' | 'name' | 'token'>,
  ) => Promise<boolean>
  onClose?: () => void
}

/**
 * The ONE Create/Join surface: full-screen for no-room recovery, dialog
 * from the rail `+`. Forms acquire the grant (create or invite join) and
 * hand the room to onRoomGranted — the navigation hook performs the JWT
 * refresh or guest descriptor insertion and the state installation. No
 * Zustand room/thread writes happen in here.
 */
export function RoomAccess({ mode, rooms, onRoomSelect, onRoomGranted, onClose }: RoomAccessProps) {
  const user = useAppStore((s) => s.user)
  const accessToken = useAppStore((s) => s.accessToken)

  const [error, setError] = useState('')

  const [showCreate, setShowCreate] = useState(false)
  const [newRoomName, setNewRoomName] = useState('')
  const [creating, setCreating] = useState(false)

  const [showJoin, setShowJoin] = useState(false)
  const [joinCode, setJoinCode] = useState('')
  const [showManualJoin, setShowManualJoin] = useState(false)
  const [joinRoomId, setJoinRoomId] = useState('')
  const [joinToken, setJoinToken] = useState('')
  const [joining, setJoining] = useState(false)
  const [enteringRoomId, setEnteringRoomId] = useState<string | null>(null)

  const handleSelectRoom = async (room: UserRoom) => {
    setError('')
    setEnteringRoomId(room.id)
    try {
      const entered = await onRoomSelect({ roomId: room.id })
      if (!entered) setError('Could not open that room. Refresh and try again.')
    } finally {
      setEnteringRoomId(null)
    }
  }

  const handleCreateRoom = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    setError('')
    setCreating(true)
    try {
      const room = await api.createRoom(newRoomName || undefined) as Room & { token: string }
      api.setToken(room.token)
      await api.joinRoom(room.id, user.id)
      const entered = await onRoomGranted({
        id: room.id, name: room.name, token: room.token,
      })
      if (!entered) throw new Error('Created the room but could not enter it')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create room')
    } finally {
      setCreating(false)
    }
  }

  const handleJoinRoom = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    setError('')
    setJoining(true)
    try {
      const invite = showManualJoin
        ? { roomId: joinRoomId.trim(), token: joinToken.trim() }
        : parseInviteCode(joinCode)

      if (!invite?.roomId || !invite.token) {
        throw new Error(showManualJoin
          ? 'Room ID and room token are both required'
          : 'Paste a valid Dialectic invite code')
      }

      api.setToken(invite.token)
      await api.joinRoom(invite.roomId, user.id)

      let roomName: string | null = null
      if (accessToken) {
        roomName = rooms.find((room) => room.id === invite.roomId)?.name ?? null
      }
      const entered = await onRoomGranted({
        id: invite.roomId, name: roomName, token: invite.token,
      })
      if (!entered) throw new Error('Joined the room but could not enter it')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to join room')
    } finally {
      setJoining(false)
    }
  }

  const body = (
    <>
      {error && <div className="room-error">{error}</div>}

      <div className="room-actions">
        <button
          className="btn btn-primary"
          onClick={() => { setShowCreate(true); setShowJoin(false) }}
        >
          + Create Room
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => {
            setShowJoin(true)
            setShowCreate(false)
            setJoinCode('')
            setJoinRoomId('')
            setJoinToken('')
            setShowManualJoin(false)
          }}
        >
          Join Room
        </button>
      </div>

      {showCreate && (
        <form className="room-form" onSubmit={handleCreateRoom}>
          <label className="auth-label">
            Room Name
            <input
              className="form-input"
              type="text"
              value={newRoomName}
              onChange={(e) => setNewRoomName(e.target.value)}
              placeholder="Optional room name"
              autoFocus
            />
          </label>
          <div className="room-form-actions">
            <button className="btn btn-primary" type="submit" disabled={creating}>
              {creating ? 'Creating...' : 'Create'}
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {showJoin && (
        <form className="room-form" onSubmit={handleJoinRoom}>
          {!showManualJoin ? (
            <label className="auth-label">
              Invite Code
              <input
                className="form-input"
                type="text"
                value={joinCode}
                onChange={(e) => setJoinCode(e.target.value)}
                placeholder="dialectic-v1:room-id:token"
                required
                autoFocus
                autoComplete="off"
              />
            </label>
          ) : (
            <>
              <label className="auth-label">
                Room ID
                <input
                  className="form-input"
                  type="text"
                  value={joinRoomId}
                  onChange={(e) => setJoinRoomId(e.target.value)}
                  placeholder="Paste room ID"
                  required
                  autoFocus
                  autoComplete="off"
                />
              </label>
              <label className="auth-label">
                Room Token
                <input
                  className="form-input"
                  type="password"
                  value={joinToken}
                  onChange={(e) => setJoinToken(e.target.value)}
                  placeholder="Paste room token"
                  required
                  autoComplete="off"
                />
              </label>
            </>
          )}
          <button
            className="btn btn-ghost btn-sm"
            type="button"
            onClick={() => setShowManualJoin((value) => !value)}
          >
            {showManualJoin ? 'Use invite code' : 'Enter room ID and token manually'}
          </button>
          <div className="room-form-actions">
            <button className="btn btn-primary" type="submit" disabled={joining}>
              {joining ? 'Joining...' : 'Join'}
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => setShowJoin(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="room-list">
        <h2 className="room-list-title">Your Rooms</h2>
        {rooms.length === 0 && (
          <p className="room-empty">No rooms yet. Create one or join with an invite code.</p>
        )}
        {rooms.map((room) => (
          <button
            key={room.id}
            className="room-item"
            onClick={() => void handleSelectRoom(room)}
            disabled={enteringRoomId !== null}
          >
            <div className="room-item-header">
              <span className="room-item-name">
                {enteringRoomId === room.id
                  ? 'Opening…'
                  : (room.is_home ? 'Home' : (room.name ?? 'Unnamed Room'))}
              </span>
              {room.unread_count > 0 && (
                <span className="room-item-badge">{room.unread_count}</span>
              )}
            </div>
            {room.last_message_preview && (
              <p className="room-item-preview">{room.last_message_preview}</p>
            )}
          </button>
        ))}
      </div>
    </>
  )

  if (mode === 'dialog') {
    return (
      <div className="room-access-overlay" role="dialog" aria-modal="true">
        <div className="room-access-scrim" onClick={onClose} aria-hidden="true" />
        <div className="room-card room-access-dialog">
          <div className="room-access-dialog-head">
            <h2 className="room-list-title">Rooms</h2>
            <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">
              ×
            </button>
          </div>
          {body}
        </div>
      </div>
    )
  }
  return body
}
