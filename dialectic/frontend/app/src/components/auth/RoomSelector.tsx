import { useState, useEffect, useCallback } from 'react'
import { useAppStore } from '../../stores/appStore.ts'
import { api } from '../../lib/api.ts'
import type { UserRoom, Room, Thread } from '../../types/index.ts'
import './RoomSelector.css'

export function RoomSelector() {
  const user = useAppStore((s) => s.user);
  const setRoom = useAppStore((s) => s.setRoom);
  const setThread = useAppStore((s) => s.setThread);
  const setThreads = useAppStore((s) => s.setThreads);
  const logout = useAppStore((s) => s.logout);

  const [rooms, setRooms] = useState<UserRoom[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Create room
  const [showCreate, setShowCreate] = useState(false);
  const [newRoomName, setNewRoomName] = useState('');
  const [creating, setCreating] = useState(false);

  // Join room
  const [showJoin, setShowJoin] = useState(false);
  const [joinRoomId, setJoinRoomId] = useState('');
  const [joinToken, setJoinToken] = useState('');
  const [joining, setJoining] = useState(false);

  const fetchRooms = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const data = await api.getRooms(user.id) as UserRoom[];
      setRooms(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load rooms');
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    void fetchRooms();
  }, [fetchRooms]);

  const handleSelectRoom = async (room: UserRoom) => {
    setError('');
    try {
      // We need the room token to connect. Fetch room details or use stored token.
      // The /rooms endpoint returns token on create, and /rooms/{id}/join also uses token.
      // For existing memberships, we need to get the token from the room.
      // Use a direct fetch to get the room token via join (already member returns status).
      // Actually, we need the token. Let's fetch threads which requires token.
      // The simplest approach: store room tokens when joining. For now, prompt for token.

      // For rooms the user is already a member of, we need their token.
      // The backend's UserRoomResponse doesn't include the token.
      // We'll fetch it by trying to get threads with the room.
      // Workaround: use the room ID as a key to get the token from a lookup.

      // NOTE: The backend doesn't expose room tokens for existing memberships via GET.
      // This is a known gap. For now, we'll ask the user for the token when selecting.
      // A proper fix would add token to UserRoomResponse or a dedicated endpoint.

      setJoinRoomId(room.id);
      setShowJoin(true);
      setShowCreate(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to select room');
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
      api.setToken(joinToken);
      await api.joinRoom(joinRoomId, user.id);

      // Get threads
      const threads = await api.getThreads(joinRoomId) as Thread[];
      setRoom({ id: joinRoomId, name: null, token: joinToken }, joinToken);
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
          <button className="btn btn-ghost btn-sm" onClick={logout}>
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
            onClick={() => { setShowJoin(true); setShowCreate(false); setJoinRoomId(''); }}
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
              />
            </label>
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
            <p className="room-empty">No rooms yet. Create one or join with a token.</p>
          )}
          {rooms.map((room) => (
            <button
              key={room.id}
              className="room-item"
              onClick={() => handleSelectRoom(room)}
            >
              <div className="room-item-header">
                <span className="room-item-name">
                  {room.name ?? 'Unnamed Room'}
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
