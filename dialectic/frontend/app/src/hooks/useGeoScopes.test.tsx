import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api.ts'
import type { GeoProjection } from '../types/geo.ts'
import { useGeoScopes } from './useGeoScopes.ts'

function projection(label: string): GeoProjection {
  return { generated_at: label, room_id: 'room-h', scopes: [] }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useGeoScopes', () => {
  it('queues a refresh while loading and prevents the stale request from winning', async () => {
    const stale = deferred<GeoProjection>()
    const fresh = deferred<GeoProjection>()
    vi.spyOn(api, 'getGeo')
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise)

    const { result } = renderHook(() => useGeoScopes('room-h'))
    await waitFor(() => expect(api.getGeo).toHaveBeenCalledTimes(1))
    expect(result.current.status).toBe('loading')

    act(() => { result.current.retry() })
    await waitFor(() => expect(api.getGeo).toHaveBeenCalledTimes(2))

    await act(async () => { stale.resolve(projection('before-write')); await stale.promise })
    expect(result.current.status).toBe('loading')

    await act(async () => { fresh.resolve(projection('after-write')); await fresh.promise })
    await waitFor(() => expect(result.current.status).toBe('ready'))
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.projection.generated_at).toBe('after-write')
  })
})
