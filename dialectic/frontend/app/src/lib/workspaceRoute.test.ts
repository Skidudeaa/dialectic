import { describe, expect, it } from 'vitest'
import type { Thread, UserRoom } from '../types'
import {
  destinationFromLocation,
  destinationFromSearch,
  destinationUrl,
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
    expect(destinationFromSearch('')).toEqual({ roomId: null, threadId: null })
  })

  it('reads room and branch destinations', () => {
    expect(destinationFromSearch('?room=scheme-room')).toEqual({
      roomId: 'scheme-room',
      threadId: null,
    })
    expect(destinationFromSearch('?room=scheme-room&thread=branch-thread')).toEqual({
      roomId: 'scheme-room',
      threadId: 'branch-thread',
    })
  })

  it('uses only the Location search field', () => {
    expect(destinationFromLocation({
      search: '?room=scheme-room&thread=branch-thread',
    })).toEqual({
      roomId: 'scheme-room',
      threadId: 'branch-thread',
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
