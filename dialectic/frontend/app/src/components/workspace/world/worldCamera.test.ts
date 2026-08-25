import { describe, expect, it } from 'vitest'
import { decodeWorldView, encodeWorldView, isWorldView } from './worldCamera'

describe('the world view grammar', () => {
  it('recognises World mode with and without a camera', () => {
    expect(isWorldView('world')).toBe(true)
    expect(isWorldView('world:26.5,56.3,450000,0,-45')).toBe(true)
    expect(isWorldView('world;room=abc')).toBe(true)
    expect(isWorldView(null)).toBe(false)
    expect(isWorldView('worldly')).toBe(false)
    expect(isWorldView('house')).toBe(false)
  })

  it('round-trips a camera at share-link precision', () => {
    const encoded = encodeWorldView({
      camera: { lat: 26.54321, lon: 56.31234, alt: 450000.6, heading: 12.4, pitch: -44.6 },
      roomId: null,
    })
    expect(encoded).toBe('world:26.5432,56.3123,450001,12,-45')
    expect(decodeWorldView(encoded)).toEqual({
      camera: { lat: 26.5432, lon: 56.3123, alt: 450001, heading: 12, pitch: -45 },
      roomId: null,
    })
  })

  it('carries a room prefocus beside the camera', () => {
    const encoded = encodeWorldView({ camera: null, roomId: 'r1' })
    expect(encoded).toBe('world;room=r1')
    expect(decodeWorldView(encoded)).toEqual({ camera: null, roomId: 'r1' })
    expect(decodeWorldView('world:1,2,300,0,-30;room=r2')).toEqual({
      camera: { lat: 1, lon: 2, alt: 300, heading: 0, pitch: -30 }, roomId: 'r2',
    })
  })

  it('degrades an undecodable camera to the default view, never an error', () => {
    expect(decodeWorldView('world:1,2,3')).toEqual({ camera: null, roomId: null })
    expect(decodeWorldView('world:91,0,100,0,0')).toEqual({ camera: null, roomId: null })
    expect(decodeWorldView('world:1,2,-5,0,0')).toEqual({ camera: null, roomId: null })
    expect(decodeWorldView('world:a,b,c,d,e')).toEqual({ camera: null, roomId: null })
    expect(decodeWorldView('not-a-view')).toBeNull()
  })
})
