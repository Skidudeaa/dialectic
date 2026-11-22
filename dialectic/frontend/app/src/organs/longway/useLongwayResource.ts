import { useCallback, useEffect, useState } from 'react'
import { longwayRequest } from './api'

export function useLongwayResource<T>(path: string | null, refreshKey = '', interval = 0) {
  return useResource<T>(path, refreshKey, interval, true)
}

// A film and its editing baseline stay fixed until the member reopens or saves.
export function useLongwaySnapshot<T>(path: string) {
  return useResource<T>(path, '', 0, false)
}

function useResource<T>(path: string | null, refreshKey: string, interval: number, live: boolean) {
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
        const data = await longwayRequest<T>(path, { signal: controller.signal, cache: live ? 'default' : 'no-store' })
        if (!controller.signal.aborted && ticket === serial) setResult({ path, data })
      } catch (error) {
        if (!controller.signal.aborted && ticket === serial) setResult(previous => ({ path, data: previous?.path === path ? previous.data : undefined, error: error instanceof Error ? error.message : 'Could not load' }))
      }
    }
    const changed = (event: Event) => { if (path.startsWith((event as CustomEvent<string>).detail)) void read() }
    if (live) window.addEventListener('longway:changed', changed)
    void read()
    const timer = interval ? window.setInterval(() => void read(), interval) : undefined
    return () => { controller.abort(); window.clearInterval(timer); window.removeEventListener('longway:changed', changed) }
  }, [path, refreshKey, interval, version, live])
  // Apply a confirmed write immediately, including while the projection re-reads.
  const update = useCallback((apply: (data: T) => T) => {
    setResult(previous => previous && previous.path === path && previous.data !== undefined
      ? { ...previous, data: apply(previous.data) } : previous)
  }, [path])
  const current = result?.path === path ? result : null
  return { data: current?.data, error: current?.error, loading: Boolean(path && !current), refresh, update }
}
