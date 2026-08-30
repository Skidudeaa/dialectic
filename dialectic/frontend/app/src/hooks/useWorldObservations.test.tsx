import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api.ts'
import type { WorldObservationsProjection } from '../types/geo.ts'
import { useWorldObservations } from './useWorldObservations.ts'

function projection(label: string): WorldObservationsProjection {
  return {
    observations: [],
    counts: [{ scope_id: 's1', scope_label: label, layer: 'aircraft', count: 1, newest_at: '2026-08-30T00:00:00Z' }],
  }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('useWorldObservations', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('queues a refresh while loading and prevents the stale request from winning', async () => {
    const stale = deferred<WorldObservationsProjection>()
    const fresh = deferred<WorldObservationsProjection>()
    vi.spyOn(api, 'getWorldObservations')
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise)

    const { result } = renderHook(() => useWorldObservations('room-h'))
    await waitFor(() => expect(api.getWorldObservations).toHaveBeenCalledTimes(1))
    expect(result.current.status).toBe('loading')

    act(() => { result.current.retry() })
    await waitFor(() => expect(api.getWorldObservations).toHaveBeenCalledTimes(2))

    await act(async () => { stale.resolve(projection('before-write')); await stale.promise })
    expect(result.current.status).toBe('loading')

    await act(async () => { fresh.resolve(projection('after-write')); await fresh.promise })
    await waitFor(() => expect(result.current.status).toBe('ready'))
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.projection.counts[0].scope_label).toBe('after-write')
  })

  it('surfaces a readable error when the read fails', async () => {
    vi.spyOn(api, 'getWorldObservations').mockRejectedValue(new Error('nope'))
    const { result } = renderHook(() => useWorldObservations('room-h'))
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
    if (result.current.status !== 'unavailable') throw new Error('unreachable')
    expect(result.current.error).toBe('nope')
  })

  it('does nothing until a room id is present', () => {
    const spy = vi.spyOn(api, 'getWorldObservations')
    renderHook(() => useWorldObservations(null))
    expect(spy).not.toHaveBeenCalled()
  })

  describe('the 300s clock', () => {
    beforeEach(() => vi.useFakeTimers())

    it('refetches on its own while mounted, without a manual retry', async () => {
      const spy = vi.spyOn(api, 'getWorldObservations').mockResolvedValue(projection('r'))
      renderHook(() => useWorldObservations('room-h'))
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      expect(spy).toHaveBeenCalledTimes(1)

      await act(async () => { await vi.advanceTimersByTimeAsync(300_000) })
      expect(spy).toHaveBeenCalledTimes(2)
    })

    it('stops polling once unmounted', async () => {
      const spy = vi.spyOn(api, 'getWorldObservations').mockResolvedValue(projection('r'))
      const { unmount } = renderHook(() => useWorldObservations('room-h'))
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      unmount()
      const callsAtUnmount = spy.mock.calls.length
      await act(async () => { await vi.advanceTimersByTimeAsync(600_000) })
      expect(spy).toHaveBeenCalledTimes(callsAtUnmount)
    })
  })
})
