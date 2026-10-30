import { useEffect, useState } from 'react'
import { getRiding } from '../api'
import type { RidingData } from '../types'
import { clockTime, lateness } from './rideCard'

export function RidingNow({ roomId, onNavigate }: { roomId: string; onNavigate: (id: string) => unknown }) {
  const [snapshot, setSnapshot] = useState<{ roomId: string; rides: RidingData['rides'] } | null>(null)
  useEffect(() => {
    const abort = new AbortController()
    let busy = false
    const poll = async () => {
      if (busy) return
      busy = true
      try {
        const data = await getRiding(roomId, abort.signal)
        if (!abort.signal.aborted) setSnapshot({ roomId, rides: data.rides ?? [] })
      } catch { /* The house's other rooms remain usable when the ride feed is unavailable. */ }
      finally { busy = false }
    }
    void poll(); const timer = setInterval(() => void poll(), 60000)
    return () => { abort.abort(); clearInterval(timer) }
  }, [roomId])
  const rides = snapshot?.roomId === roomId ? snapshot.rides : []
  if (!rides.length) return null
  return <section aria-label="Riding now" className="lw-section"><h2>Riding now</h2><ul className="lw-rooms">{rides.map(r => <li key={`${r.room_id}:${r.ride.id}`}>
    <button className="lw-room" onClick={() => void onNavigate(r.room_id)}><span className="lw-room-name">{r.ride.vehicle.name}</span>
      <span className="lw-room-journey">{r.room_name} · {r.ride.state}{r.next_stop && ` · ${r.next_stop.name} ${clockTime(r.next_stop.est)}`} · {lateness(r.late_min)}</span><span className="lw-room-go" aria-hidden="true">→</span>
    </button></li>)}</ul></section>
}
