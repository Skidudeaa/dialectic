import { useState, useEffect, useCallback } from 'react'
import { useAppStore } from '../../stores/appStore.ts'
import { api } from '../../lib/api.ts'
import type { UserRoom, Room, Thread } from '../../types/index.ts'
import './RoomSelector.css'

const INVITE_PREFIX = 'dialectic-v1:'

function parseInviteCode(value: string): { roomId: string; token: string } | null {
  const trimmed = value.trim()
  if (!trimmed.startsWith(INVITE_PREFIX)) return null

  const [version, roomId, token, ...extra] = trimmed.split(':')
  if (version !== 'dialectic-v1' || !roomId || !token || extra.length > 0) return null

  return { roomId, token }
}

export function RoomSelector() {
  const user = useAppStore((s) => s.user);
  const accessToken = useAppStore((s) => s.accessToken);
  const refreshToken = useAppStore((s) => s.refreshToken);
  const setRoom = useAppStore((s) => s.setRoom);
  const setThread = useAppStore((s) => s.setThread);
  const setThreads = useAppStore((s) => s.setThreads);
  const logout = useAppStore((s) => s.logout);

  const handleLogout = useCallback(() => {
    if (refreshToken) void api.logoutSession(refreshToken).catch(() => undefined);
    logout();
  }, [refreshToken, logout]);

  const [rooms, setRooms] = useState<UserRoom[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Create room
  const [showCreate, setShowCreate] = useState(false);
  const [newRoomName, setNewRoomName] = useState('');
  const [creating, setCreating] = useState(false);

  // Join room
  const [showJoin, setShowJoin] = useState(false);
  const [joinCode, setJoinCode] = useState('');
  const [showManualJoin, setShowManualJoin] = useState(false);
  const [joinRoomId, setJoinRoomId] = useState('');
  const [joinToken, setJoinToken] = useState('');
  const [joining, setJoining] = useState(false);
  const [enteringRoomId, setEnteringRoomId] = useState<string | null>(null);

  const fetchRooms = useCallback(async () => {
    if (!user) return;
    api.setAccessToken(accessToken ?? '');
    if (!accessToken) {
      // Guest identities can still join with an invite code, but they do not
      // have a JWT-backed saved-room list.
      setRooms([]);
      setLoading(false);
      return;
    }
    setError('');
    setLoading(true);
    try {
      const data = await api.getRooms() as UserRoom[];
      setRooms(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load rooms');
    } finally {
      setLoading(false);
    }
  }, [user, accessToken]);

  useEffect(() => {
    void fetchRooms();
  }, [fetchRooms]);

  const handleSelectRoom = async (room: UserRoom) => {
    setError('');
    setEnteringRoomId(room.id);
    try {
      if (!room.token) throw new Error('This room is missing its access token. Refresh the room list and try again.');

      api.setToken(room.token);
      const threads = await api.getThreads(room.id) as Thread[];
      setRoom({ id: room.id, name: room.name, token: room.token }, room.token);
      setThreads(threads);
      if (threads.length > 0) setThread(threads[0]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to select room');
    } finally {
      setEnteringRoomId(null);
    }
  };

  const handleCreateRoom = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return;
    setError('');
    setCreating(true);
    try {
      const room = await api.createRoom(newRoomName || undefined) as Room & { token: string };
      api.setToken(room.token);

      // Join the room
      await api.joinRoom(room.id, user.id);

      // Get threads
      const threads = await api.getThreads(room.id) as Thread[];
      setRoom({ id: room.id, name: room.name, token: room.token }, room.token);
      setThreads(threads);
      if (threads.length > 0) {
        setThread(threads[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create room');
    } finally {
      setCreating(false);
    }
  };

  const handleJoinRoom = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return;
    setError('');
    setJoining(true);
    try {
      const invite = showManualJoin
        ? { roomId: joinRoomId.trim(), token: joinToken.trim() }
        : parseInviteCode(joinCode);

      if (!invite?.roomId || !invite.token) {
        throw new Error(showManualJoin
          ? 'Room ID and room token are both required'
          : 'Paste a valid Dialectic invite code');
      }

      api.setToken(invite.token);
      await api.joinRoom(invite.roomId, user.id);

      // Get threads
      const threads = await api.getThreads(invite.roomId) as Thread[];
      let roomName: string | null = null;
      if (accessToken) {
        try {
          const updatedRooms = await api.getRooms() as UserRoom[];
          setRooms(updatedRooms);
          roomName = updatedRooms.find((room) => room.id === invite.roomId)?.name ?? null;
        } catch {
          // Joining succeeded; room metadata can refresh the next time the selector opens.
        }
      }

      setRoom({ id: invite.roomId, name: roomName, token: invite.token }, invite.token);
      setThreads(threads);
      if (threads.length > 0) {
        setThread(threads[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to join room');
    } finally {
      setJoining(false);
    }
  };

  return (
    <div className="room-screen">
      <div className="room-card">
        <div className="room-header">
          <div>
            <h1 className="room-title">&#9671; Dialectic</h1>
            <p className="room-subtitle">
              Welcome, {user?.display_name ?? 'Guest'}
            </p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={handleLogout}>
            Sign Out
          </button>
        </div>

        {error && <div className="room-error">{error}</div>}

        <div className="room-actions">
          <button
            className="btn btn-primary"
            onClick={() => { setShowCreate(true); setShowJoin(false); }}
          >
            + Create Room
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => {
              setShowJoin(true);
              setShowCreate(false);
              setJoinCode('');
              setJoinRoomId('');
              setJoinToken('');
              setShowManualJoin(false);
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
          {loading && <p className="room-empty">Loading rooms...</p>}
          {!loading && rooms.length === 0 && (
            <p className="room-empty">No rooms yet. Create one or join with an invite code.</p>
          )}
          {rooms.map((room) => (
            <button
              key={room.id}
              className="room-item"
              onClick={() => handleSelectRoom(room)}
              disabled={enteringRoomId !== null}
            >
              <div className="room-item-header">
                <span className="room-item-name">
                  {enteringRoomId === room.id ? 'Opening…' : (room.name ?? 'Unnamed Room')}
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
      </div>
    </div>
  );
}
