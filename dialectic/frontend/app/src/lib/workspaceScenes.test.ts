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
  it('gives an ordinary room the surface and the six workroom scenes', () => {
    // Synapse brings the same Atlas House/World embodiment through the room;
    // it does not create a second router or move room work into Home. The
    // working surface (2026-09-02) leads the root; a branch is an ordinary
    // conversation and does not carry it.
    expect(scenesForDestination(scheme, root)).toEqual([
      'surface', 'record', 'bench', 'field', 'atlas', 'library', 'ledger',
    ])
    expect(scenesForDestination(scheme, { parent_thread_id: 'root' })).toEqual([
      'record', 'bench', 'field', 'atlas', 'library', 'ledger',
    ])
  })

  it('gives Home root the household view, the atlas, the mirror, and nothing else', () => {
    // Home coordinates; scheme rooms own scheme work (§5.5). Home cannot bind
    // a thesis at all — the API returns 409 — so a Bench there would be a door
    // onto a refusal. Atlas joins at Home root only (Release 3, §5.4): it is
    // personal cross-room navigation, so it lives where the person starts.
    // Mirror joins on the same reasoning (2026-08-20) and for the same
    // reason it can only live here: it is about the READER, not a room, and
    // it is fenced in the SQL to the caller's own model.
    expect(scenesForDestination(home, root))
      .toEqual(['house', 'atlas', 'mirror', 'record'])
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
    expect(scenesForDestination(scheme, root)[0]).toBe('surface')
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
    expect(resolveWorkspaceScene(scheme, root, 'house')).toBe('surface')
  })

  it('still falls back from approved but unbuilt scenes', () => {
    // `field` moved out of this list in Release 3 — FieldScene.tsx renders
    // it now, so it belongs in the "accepts every scene on offer" case
    // above instead. Synapse did the same for ordinary-room `atlas`.
    // `focus` is a state, not a scene, and remains outside the implemented
    // list on purpose (§5.2). (`judgment` was retired 2026-08-29.)
    expect(resolveWorkspaceScene(scheme, root, 'focus')).toBe('surface')
    expect(resolveWorkspaceScene(home, root, 'focus')).toBe('house')
  })
})
