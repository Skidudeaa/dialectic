import { useCallback, useEffect, useState } from 'react'
import { longwayRequest } from './api'

export function useLongwayResource<T>(path: string | null, refreshKey = '', interval = 0) {
  const [result, setResult] = useState<{ path: string; data?: T; error?: string } | null>(null)
  const [version, setVersion] = useState(0)
  const refresh = useCallback(() => setVersion(v => v + 1), [])
  useEffect(() => {
    if (!path) return
    const controller = new AbortController()
    let serial = 0
    const read = async () => {
      const ticket = ++serial
      try {
        const data = await longwayRequest<T>(path, { signal: controller.signal })
        if (!controller.signal.aborted && ticket === serial) setResult({ path, data })
      } catch (error) {
        if (!controller.signal.aborted && ticket === serial) setResult(previous => ({ path, data: previous?.path === path ? previous.data : undefined, error: error instanceof Error ? error.message : 'Could not load' }))
      }
    }
    const changed = (event: Event) => { if (path.startsWith((event as CustomEvent<string>).detail)) void read() }
    window.addEventListener('longway:changed', changed)
    void read()
    const timer = interval ? window.setInterval(() => void read(), interval) : undefined
    return () => { controller.abort(); window.clearInterval(timer); window.removeEventListener('longway:changed', changed) }
  }, [path, refreshKey, interval, version])
  const current = result?.path === path ? result : null
  return { data: current?.data, error: current?.error, loading: Boolean(path && !current), refresh }
}
