import { useState } from 'react'
import type { ComponentProps } from 'react'
import type { RoomAccess } from '../../components/auth/RoomAccess'
import { useAppStore } from '../../stores/appStore'
import { longwayRequest } from './api'

export function LongwayRoomAccess({ mode, rooms, onRoomSelect, onRoomGranted, onClose }: ComponentProps<typeof RoomAccess>) {
  const user = useAppStore(s => s.user)
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  return <section className="longway-room-access" role={mode === 'dialog' ? 'dialog' : undefined} aria-label="Your rooms">
    {onClose && <button onClick={onClose}>Close rooms</button>}
    <h2>Your rooms</h2>
    {rooms.map(room => <p key={room.id}><button disabled={busy} onClick={async () => {
      setBusy(true); setError('')
      try { if (!await onRoomSelect({ roomId: room.id })) setError('Could not open room.') }
      catch (error) { setError(error instanceof Error ? error.message : 'Could not open room.') }
      finally { setBusy(false) }
    }}>{room.is_home ? 'House' : room.name ?? 'Journey room'}</button></p>)}
    <p>Journey rooms are opened from the House by a house manager.</p>
    <form onSubmit={async e => {
      e.preventDefault(); setError('')
      const [version, id, token, ...rest] = code.trim().split(':')
      if (!user || version !== 'dialectic-v1' || !id || !token || rest.length) { setError('Paste a valid room invite code.'); return }
      setBusy(true)
      try {
        await longwayRequest(`/rooms/${encodeURIComponent(id)}/join`, { method: 'POST', body: JSON.stringify({ user_id: user.id }) }, token)
        if (!await onRoomGranted({ id, token, name: rooms.find(r => r.id === id)?.name ?? null })) setError('Joined the room but could not enter it. Try opening it again.')
      } catch (error) { setError(error instanceof Error ? error.message : 'Could not join room.') }
      finally { setBusy(false) }
    }}><label>Room invite code<input required value={code} onChange={e => setCode(e.target.value)} autoComplete="off" /></label><button disabled={busy}>Join room</button></form>
    {error && <p role="alert">{error}</p>}
  </section>
}
