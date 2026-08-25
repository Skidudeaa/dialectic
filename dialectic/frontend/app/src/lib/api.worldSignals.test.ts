import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api.ts'

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response
}

afterEach(() => {
  api.setAccessToken('')
  api.setRoomToken('')
  vi.unstubAllGlobals()
})

describe('WorldSignal placement capability', () => {
  it('overrides the current room token for this bodyless target-room request only', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ id: 'geo_scope:placed' }))
    vi.stubGlobal('fetch', fetch)
    api.setAccessToken('jwt')
    api.setRoomToken('home-token')

    await api.placeWorldSignal(
      'room-target', 'world_signal:ais:contact-1', 'target-room-token',
    )
    await api.getGeo('room-home')

    expect(fetch.mock.calls[0][0]).toBe(
      '/rooms/room-target/world-signals/world_signal%3Aais%3Acontact-1/place',
    )
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      headers: expect.objectContaining({
        Authorization: 'Bearer jwt',
        'X-Room-Token': 'target-room-token',
      }),
    })
    expect(fetch.mock.calls[0][1]).not.toHaveProperty('body')
    expect(fetch.mock.calls[1][1].headers).toEqual(expect.objectContaining({
      'X-Room-Token': 'home-token',
    }))
  })
})
