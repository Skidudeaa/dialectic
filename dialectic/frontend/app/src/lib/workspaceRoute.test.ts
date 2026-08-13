import { describe, expect, it } from 'vitest'
import type { Thread, UserRoom } from '../types'
import {
  defaultWorkspaceScene,
  destinationFromLocation,
  destinationFromSearch,
  destinationUrl,
  resolveWorkspaceScene,
} from './workspaceRoute'

const home = {
  id: 'home-room',
  is_home: true,
} as Pick<UserRoom, 'id' | 'is_home'>

const scheme = {
  id: 'scheme-room',
  is_home: false,
} as Pick<UserRoom, 'id' | 'is_home'>

const root = {
  id: 'main-thread',
  parent_thread_id: null,
} as Pick<Thread, 'id' | 'parent_thread_id'>

const branch = {
  id: 'branch-thread',
  parent_thread_id: 'main-thread',
} as Pick<Thread, 'id' | 'parent_thread_id'>

describe('destinationFromSearch', () => {
  it('treats a bare URL as the canonical Home destination', () => {
    expect(destinationFromSearch('')).toEqual({
      roomId: null,
      threadId: null,
      scene: null,
    })
  })

  it('reads room and branch destinations', () => {
    expect(destinationFromSearch('?room=scheme-room')).toEqual({
      roomId: 'scheme-room',
      threadId: null,
      scene: null,
    })
    expect(destinationFromSearch('?room=scheme-room&thread=branch-thread')).toEqual({
      roomId: 'scheme-room',
      threadId: 'branch-thread',
      scene: null,
    })
  })

  it('uses only the Location search field', () => {
    expect(destinationFromLocation({
      search: '?room=scheme-room&thread=branch-thread',
    })).toEqual({
      roomId: 'scheme-room',
      threadId: 'branch-thread',
      scene: null,
    })
  })
})

describe('destinationUrl', () => {
  it('canonicalizes only the Home root to a bare slash', () => {
    expect(destinationUrl(home, root)).toBe('/')
    expect(destinationUrl(home, branch)).toBe(
      '/?room=home-room&thread=branch-thread',
    )
  })

  it('keeps ordinary roots and branches explicit', () => {
    expect(destinationUrl(scheme, root)).toBe('/?room=scheme-room')
    expect(destinationUrl(scheme, branch)).toBe(
      '/?room=scheme-room&thread=branch-thread',
    )
  })
})

describe('workspace scenes', () => {
  it('parses known scene names and drops unknown names', () => {
    expect(destinationFromSearch('?scene=record')).toEqual({
      roomId: null,
      threadId: null,
      scene: 'record',
    })
    expect(destinationFromSearch('?scene=made-up')).toEqual({
      roomId: null,
      threadId: null,
      scene: null,
    })
  })

  it('defaults Home root to House and every other destination to Record', () => {
    expect(defaultWorkspaceScene(home, root)).toBe('house')
    expect(defaultWorkspaceScene(home, branch)).toBe('record')
    expect(defaultWorkspaceScene(scheme, root)).toBe('record')
    expect(defaultWorkspaceScene(scheme, branch)).toBe('record')
  })

  it('rejects an invalid House request outside Home root', () => {
    expect(resolveWorkspaceScene(scheme, root, 'house')).toBe('record')
    expect(resolveWorkspaceScene(home, branch, 'house')).toBe('record')
  })

  it('falls back from approved but not-yet-implemented scenes', () => {
    expect(resolveWorkspaceScene(home, root, 'field')).toBe('house')
    expect(resolveWorkspaceScene(scheme, root, 'library')).toBe('record')
  })

  it('omits the default scene and serializes only a non-default scene', () => {
    expect(destinationUrl(home, root, 'house')).toBe('/')
    expect(destinationUrl(home, root, 'record')).toBe('/?scene=record')
    expect(destinationUrl(scheme, root, 'record')).toBe('/?room=scheme-room')
    expect(destinationUrl(home, branch, 'record')).toBe(
      '/?room=home-room&thread=branch-thread',
    )
  })
})
