import { describe, expect, it } from 'vitest'
import type { Thread, UserRoom } from '../types'
import {
  defaultWorkspaceScene,
  entryDestination,
  destinationFromLocation,
  destinationFromSearch,
  destinationUrl,
  resolveWorkspaceScene,
  scenesForDestination,
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
  it('reads an exact message destination', () => {
    expect(destinationFromSearch('?room=r&thread=t&message=m')).toMatchObject({
      roomId: 'r',
      threadId: 't',
      messageId: 'm',
    })
  })

  it('treats a bare URL as the canonical Home destination', () => {
    expect(destinationFromSearch('')).toEqual({
      roomId: null,
      threadId: null,
      scene: null,
      object: null,
      messageId: null,
    })
  })

  it('reads room and branch destinations', () => {
    expect(destinationFromSearch('?room=scheme-room')).toEqual({
      roomId: 'scheme-room',
      threadId: null,
      scene: null,
      object: null,
      messageId: null,
    })
    expect(destinationFromSearch('?room=scheme-room&thread=branch-thread')).toEqual({
      roomId: 'scheme-room',
      threadId: 'branch-thread',
      scene: null,
      object: null,
      messageId: null,
    })
  })

  it('uses only the Location search field', () => {
    expect(destinationFromLocation({
      search: '?room=scheme-room&thread=branch-thread',
    })).toEqual({
      roomId: 'scheme-room',
      threadId: 'branch-thread',
      scene: null,
      object: null,
      messageId: null,
    })
  })
})

describe('the object axis (§1.18)', () => {
  it('reads an object id alongside a room and branch', () => {
    expect(destinationFromSearch('?room=scheme-room&object=field_mark:abc')).toEqual({
      roomId: 'scheme-room',
      threadId: null,
      scene: null,
      object: 'field_mark:abc',
      messageId: null,
    })
  })

  it('round-trips through destinationUrl', () => {
    expect(
      destinationUrl(scheme, root, 'field', 'field_mark:abc'),
    ).toBe('/?room=scheme-room&scene=field&object=field_mark%3Aabc')
    expect(
      destinationFromSearch('?room=scheme-room&scene=field&object=field_mark%3Aabc'),
    ).toEqual({
      roomId: 'scheme-room',
      threadId: null,
      scene: 'field',
      object: 'field_mark:abc',
      messageId: null,
    })
  })

  it('omits the object param when none is selected', () => {
    expect(destinationUrl(scheme, root)).toBe('/?room=scheme-room')
  })
})

describe('destinationUrl', () => {
  it('serializes an exact message without changing legacy destinations', () => {
    expect(destinationUrl(scheme, branch, 'record', null, 'message-id')).toBe(
      '/?room=scheme-room&thread=branch-thread&message=message-id',
    )
    expect(destinationUrl(scheme, branch)).toBe(
      '/?room=scheme-room&thread=branch-thread',
    )
  })

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
      object: null,
      messageId: null,
    })
    expect(destinationFromSearch('?scene=made-up')).toEqual({
      roomId: null,
      threadId: null,
      scene: null,
      object: null,
      messageId: null,
    })
  })

  it('offers Field in an ordinary room but never at Home root', () => {
    // THE one scenesForDestination definition (§5.2) — Field joins Bench
    // between Bench and Library; Home holds no Field at all.
    expect(scenesForDestination(scheme, root)).toEqual([
      'record', 'bench', 'field', 'library', 'ledger',
    ])
    expect(scenesForDestination(home, root)).toEqual(['house', 'atlas', 'record'])
    expect(scenesForDestination(home, branch)).toEqual(['record'])
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
    // `library` was the example here until Release 2 built it. The assertion
    // is about the FALLBACK, so it needs a scene that is still only a name —
    // production holds zero commitments and zero briefs, so Judgment and the
    // rest stay unbuilt on purpose.
    expect(resolveWorkspaceScene(home, root, 'field')).toBe('house')
    expect(resolveWorkspaceScene(scheme, root, 'judgment')).toBe('record')
  })

  it('canonicalizes a known but unavailable scene back to the destination default', () => {
    const resolved = resolveWorkspaceScene(home, root, 'field')
    expect(resolved).toBe('house')
    expect(destinationUrl(home, root, resolved)).toBe('/')
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

describe('entryDestination', () => {
  it('keeps an explicit room destination untouched', () => {
    const parsed = { roomId: 'scheme-room', threadId: 'branch-thread', scene: 'record' as const, object: null }
    expect(entryDestination(parsed)).toEqual(parsed)
  })

  it('preserves the requested scene when falling back to Home root', () => {
    // Regression: boot and popstate rebuilt the Home-root destination as
    // { roomId: null, threadId: null } and silently dropped the scene, so
    // /?scene=record reloaded into House.
    expect(entryDestination({ roomId: null, threadId: null, scene: 'record' })).toEqual({
      roomId: null,
      threadId: null,
      scene: 'record',
      object: null,
      messageId: null,
    })
  })

  it('carries no scene when none was requested', () => {
    expect(entryDestination({ roomId: null, threadId: null, scene: null })).toEqual({
      roomId: null,
      threadId: null,
      scene: null,
      object: null,
      messageId: null,
    })
  })

  it('preserves a selected object when falling back to Home root, same as scene', () => {
    // The object axis must not silently drop the same way the scene once did
    // (see the regression above) — Focus can be open at Home root too, since
    // house movements are workspace objects.
    expect(entryDestination({
      roomId: null, threadId: null, scene: null, object: 'house_movement:x',
    })).toEqual({
      roomId: null,
      threadId: null,
      scene: null,
      object: 'house_movement:x',
      messageId: null,
    })
  })
})
