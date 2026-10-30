import { useEffect, useState } from 'react'
import { getRide, getRideLeg } from '../api'
import type { RideData, RideLeg } from '../types'

export function useRide(roomId: string, selectedRide?: string) {
  const [snapshot, setSnapshot] = useState<{ key: string; data: RideData } | null>(null)
  const [model, setModel] = useState<{ key: string; data: RideLeg } | null>(null)
  const [error, setError] = useState('')
  const [legError, setLegError] = useState('')
  const [retry, setRetry] = useState(0)
  const [now, setNow] = useState(Date.now)
  const key = `${roomId}:${selectedRide ?? ''}`
  const data = snapshot?.key === key ? snapshot.data : null
  const legKey = `${roomId}:${data?.ride.leg ?? ''}`
  const leg = model?.key === legKey ? model.data : null
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    const abort = new AbortController()
    let busy = false, arrived = false
    setError('')
    async function poll() {
      if (busy || arrived) return
      busy = true
      try {
        const result = await getRide(roomId, selectedRide, abort.signal)
        if (!abort.signal.aborted) {
          setSnapshot({ key, data: result }); setError(''); setNow(Date.now())
          arrived = result.ride.state === 'arrived'
        }
      } catch (e) {
        if (!abort.signal.aborted) setError(e instanceof Error ? e.message : 'Ride unavailable')
      } finally { busy = false }
    }
    void poll()
    const timer = setInterval(() => void poll(), 60000)
    const resume = () => { void poll() }
    window.addEventListener('online', resume)
    return () => { abort.abort(); clearInterval(timer); window.removeEventListener('online', resume) }
  }, [roomId, selectedRide, key, retry])
  useEffect(() => {
    const abort = new AbortController()
    setLegError('')
    if (data?.ride.leg && data.ride.leg_ready) {
      void getRideLeg(roomId, data.ride.leg, abort.signal).then(result => {
        if (abort.signal.aborted) return
        setModel({ key: legKey, data: result })
        // Fetch while connected, including photos beyond the next six card rows.
        for (const entry of Object.values(result.guide ?? {})) {
          if (entry.img?.startsWith('https://')) { const img = new Image(); img.src = entry.img }
        }
      }).catch(e => { if (!abort.signal.aborted) setLegError(e instanceof Error ? e.message : 'Leg unavailable') })
    }
    return () => abort.abort()
  }, [roomId, legKey, data?.ride.leg, data?.ride.leg_ready, retry])
  // Cached /ride responses keep their server timestamp: receiving cached bytes is not a successful refresh.
  const lastSuccess = data ? Math.min(now, Date.parse(data.fetched_at)) : null
  const offline = data?.ride.state === 'riding' && lastSuccess !== null && now - lastSuccess > 120000
  return { data, leg, error, legError, now, offline, lastSuccess, refresh: () => setRetry(n => n + 1) }
}
