import { describe, expect, it } from 'vitest'
import type { Thread, UserRoom } from '../types'
import { scenesForDestination } from './workspaceRoute'
import { resolveWorkspaceScene } from './workspaceRoute'
import { IMPLEMENTED_WORKSPACE_SCENES } from '../types/workspace.ts'

/**
 * Release 2 makes the scenes real for ordinary rooms. Release 1 shipped only
 * House and Record, so an ordinary room showed no switcher at all and the
 * workspace-object projection — a whole shipped subsystem — had nowhere to
 * render.
 *
 * The rule this file pins is that ONE function answers "what can this
 * destination show", and both the router and the frame read it. They used to
 * answer separately: resolveWorkspaceScene rejected `house` outside Home root,
 * and WorkspaceSceneFrame independently hardcoded the same rule. Two copies of
 * a rule is how the identity name drifted three ways; this one gets a single
 * definition before it has a chance to.
 */

const home = { id: 'home-room', is_home: true } as Pick<UserRoom, 'id' | 'is_home'>
const scheme = { id: 'scheme-room', is_home: false } as Pick<UserRoom, 'id' | 'is_home'>
const root = { id: 'main', parent_thread_id: null } as Pick<Thread, 'id' | 'parent_thread_id'>
const branch = { id: 'br', parent_thread_id: 'main' } as Pick<Thread, 'id' | 'parent_thread_id'>

describe('scenesForDestination', () => {
  it('gives an ordinary room the four workroom scenes', () => {
    expect(scenesForDestination(scheme, root)).toEqual([
      'record', 'bench', 'library', 'ledger',
    ])
  })

  it('gives Home root the household view and its table, and nothing else', () => {
    // Home coordinates; scheme rooms own scheme work (§5.5). Home cannot bind
    // a thesis at all — the API returns 409 — so a Bench there would be a door
    // onto a refusal.
    expect(scenesForDestination(home, root)).toEqual(['house', 'record'])
  })

  it('treats a Home branch as an ordinary conversation', () => {
    // A branch off Home is a conversation, not the household.
    expect(scenesForDestination(home, branch)).toEqual(['record'])
  })

  it('never offers a scene that is not implemented', () => {
    for (const dest of [[scheme, root], [home, root], [home, branch]] as const) {
      for (const scene of scenesForDestination(dest[0], dest[1])) {
        expect(IMPLEMENTED_WORKSPACE_SCENES as readonly string[]).toContain(scene)
      }
    }
  })

  it('always leads with the destination default', () => {
    // The first entry is what a bare URL opens, so the list doubles as the
    // switcher's order and cannot disagree with defaultWorkspaceScene.
    expect(scenesForDestination(home, root)[0]).toBe('house')
    expect(scenesForDestination(scheme, root)[0]).toBe('record')
  })
})

describe('resolveWorkspaceScene agrees with what is on offer', () => {
  it('accepts every scene the destination offers', () => {
    for (const dest of [[scheme, root], [home, root], [home, branch]] as const) {
      for (const scene of scenesForDestination(dest[0], dest[1])) {
        expect(resolveWorkspaceScene(dest[0], dest[1], scene)).toBe(scene)
      }
    }
  })

  it('rejects every scene the destination does not offer', () => {
    // The router must not accept what the switcher will not show, or a URL
    // could install a scene with no way back to it.
    expect(resolveWorkspaceScene(home, root, 'bench')).toBe('house')
    expect(resolveWorkspaceScene(home, root, 'library')).toBe('house')
    expect(resolveWorkspaceScene(home, root, 'ledger')).toBe('house')
    expect(resolveWorkspaceScene(home, branch, 'bench')).toBe('record')
    expect(resolveWorkspaceScene(scheme, root, 'house')).toBe('record')
  })

  it('still falls back from approved but unbuilt scenes', () => {
    expect(resolveWorkspaceScene(scheme, root, 'field')).toBe('record')
    expect(resolveWorkspaceScene(scheme, root, 'atlas')).toBe('record')
    expect(resolveWorkspaceScene(home, root, 'focus')).toBe('house')
  })
})
