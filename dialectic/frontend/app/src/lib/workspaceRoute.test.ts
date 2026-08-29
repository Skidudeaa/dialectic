import { describe, expect, it } from 'vitest'
import type { Thread, UserRoom } from '../types'
import {
  defaultWorkspaceScene,
  entryDestination,
  destinationFromLocation,
  destinationFromSearch,
  destinationUrl,
  resolveWorkspaceScene,
  sceneAfterFocusNavigate,
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
      view: null,
    })
  })

  it('treats a bare URL as the canonical Home destination', () => {
    expect(destinationFromSearch('')).toEqual({
      roomId: null,
      threadId: null,
      scene: null,
      object: null,
      messageId: null,
      view: null,
    })
  })

  it('reads room and branch destinations', () => {
    expect(destinationFromSearch('?room=scheme-room')).toEqual({
      roomId: 'scheme-room',
      threadId: null,
      scene: null,
      object: null,
      messageId: null,
      view: null,
    })
    expect(destinationFromSearch('?room=scheme-room&thread=branch-thread')).toEqual({
      roomId: 'scheme-room',
      threadId: 'branch-thread',
      scene: null,
      object: null,
      messageId: null,
      view: null,
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
      view: null,
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
      view: null,
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
      view: null,
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
    expect(destinationUrl(scheme, root, 'record', null, 'root-message')).toBe(
      '/?room=scheme-room&thread=main-thread&message=root-message',
    )
    expect(destinationUrl(home, root, 'house', null, 'home-message')).toBe(
      '/?room=home-room&thread=main-thread&message=home-message',
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
      view: null,
    })
    expect(destinationFromSearch('?scene=made-up')).toEqual({
      roomId: null,
      threadId: null,
      scene: null,
      object: null,
      messageId: null,
      view: null,
    })
  })

  it('offers Field in an ordinary room but never at Home root', () => {
    // THE one scenesForDestination definition (§5.2) — Field joins Bench
    // between Bench and Library; Home holds no Field at all.
    expect(scenesForDestination(scheme, root)).toEqual([
      'record', 'bench', 'field', 'atlas', 'library', 'ledger',
    ])
    expect(scenesForDestination(home, root))
      .toEqual(['house', 'atlas', 'mirror', 'record'])
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
    expect(resolveWorkspaceScene(scheme, root, 'focus')).toBe('record')
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
      view: null,
    })
  })

  it('carries no scene when none was requested', () => {
    expect(entryDestination({ roomId: null, threadId: null, scene: null })).toEqual({
      roomId: null,
      threadId: null,
      scene: null,
      object: null,
      messageId: null,
      view: null,
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
      view: null,
    })
  })
})

describe('the view axis (World Lens)', () => {
  it('reads an opaque view beside the scene and round-trips it', () => {
    const parsed = destinationFromSearch('?scene=atlas&view=world%3A26.5%2C56.3%2C450000%2C0%2C-45')
    expect(parsed.scene).toBe('atlas')
    expect(parsed.view).toBe('world:26.5,56.3,450000,0,-45')
    const home = { id: 'home', is_home: true }
    const root = { id: 't', parent_thread_id: null }
    const url = destinationUrl(home, root, 'atlas', null, null, parsed.view)
    expect(url).toBe('/?scene=atlas&view=world%3A26.5%2C56.3%2C450000%2C0%2C-45')
    expect(destinationFromSearch(url.slice(1)).view).toBe(parsed.view)
  })

  it('omits the view param when none is set, so every older URL serializes as before', () => {
    const home = { id: 'home', is_home: true }
    const root = { id: 't', parent_thread_id: null }
    expect(destinationUrl(home, root, 'atlas')).toBe('/?scene=atlas')
    expect(destinationFromSearch('?scene=atlas').view).toBeNull()
  })

  it('survives the Home-root entry fallback', () => {
    const parsed = destinationFromSearch('?scene=atlas&view=world')
    expect(entryDestination(parsed).view).toBe('world')
  })
})

describe('Focus "Open branch"', () => {
  // The bug this pins: from Library the thread changed but the scene stayed
  // `library`, so the transcript never appeared (audit 2026-08-29).
  it('lands on the Record when a thread is named', () => {
    expect(sceneAfterFocusNavigate('library', 't1')).toBe('record')
    expect(sceneAfterFocusNavigate('field', 't1')).toBe('record')
  })

  it('keeps the scene for object-only moves', () => {
    expect(sceneAfterFocusNavigate('library', undefined)).toBe('library')
  })
})
