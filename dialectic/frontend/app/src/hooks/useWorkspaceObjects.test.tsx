import { renderHook, waitFor, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useWorkspaceObjects } from './useWorkspaceObjects'
import { api } from '../lib/api.ts'
import type { WorkspaceObject } from '../types/workspace.ts'

vi.mock('../lib/api.ts', () => ({
  api: { getWorkspaceObjects: vi.fn() },
}))

/**
 * The three states exist because design v2 §7.5 forbids collapsing them: "No
 * empty automated run should be rendered as evidence that nothing happened."
 *
 * A hook that returns `objects: []` for both "this room holds nothing" and
 * "the projection failed" makes that rule impossible to honour downstream --
 * the surface cannot tell an honest silence from a broken one, so it picks the
 * reassuring reading and shows an empty shelf over a failed fetch.
 */

const object = (kind: WorkspaceObject['kind'], id: string): WorkspaceObject => ({
  id, kind,
  room_id: 'r1', branch_id: null,
  title: `${kind} ${id}`, summary: 'a summary', status: 'active',
  created_at: '2026-08-13T10:00:00Z', updated_at: '2026-08-13T10:00:00Z',
  provenance: { origin: 'human', actor_user_id: null, detail: null },
  relationships: [], available_actions: [], review_state: 'none',
  source_entity: [], source_event: null,
})

describe('useWorkspaceObjects', () => {
  beforeEach(() => vi.clearAllMocks())

  it('starts in loading, never in empty', () => {
    vi.mocked(api.getWorkspaceObjects).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useWorkspaceObjects('r1', true))
    // An in-flight fetch that reports "nothing here" is the exact lie §7.5
    // forbids, and it is the state a surface spends most of its life in.
    expect(result.current.status).toBe('loading')
  })

  it('reports ready with the objects it received', async () => {
    vi.mocked(api.getWorkspaceObjects).mockResolvedValue({
      generated_at: '2026-08-13T10:00:00Z',
      room_id: 'r1',
      objects: [object('reading', 'a'), object('dossier_entry', 'b')],
    })
    const { result } = renderHook(() => useWorkspaceObjects('r1', true))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.objects).toHaveLength(2)
  })

  it('distinguishes a genuinely empty room from a failure', async () => {
    vi.mocked(api.getWorkspaceObjects).mockResolvedValue({
      generated_at: '2026-08-13T10:00:00Z', room_id: 'r1', objects: [],
    })
    const { result } = renderHook(() => useWorkspaceObjects('r1', true))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.objects).toEqual([])
  })

  it('reports unavailable when the projection fails, not empty', async () => {
    vi.mocked(api.getWorkspaceObjects).mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useWorkspaceObjects('r1', true))
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
  })

  it('can retry a failure', async () => {
    vi.mocked(api.getWorkspaceObjects).mockRejectedValueOnce(new Error('boom'))
    vi.mocked(api.getWorkspaceObjects).mockResolvedValue({
      generated_at: 'x', room_id: 'r1', objects: [object('reading', 'a')],
    })
    const { result } = renderHook(() => useWorkspaceObjects('r1', true))
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
    if (result.current.status !== 'unavailable') throw new Error('unreachable')
    // Captured OUTSIDE act: TypeScript's narrowing does not survive into the
    // closure, and re-reading result.current there is the union again.
    const { retry } = result.current
    await act(async () => { retry() })
    await waitFor(() => expect(result.current.status).toBe('ready'))
  })

  it('does not fetch until it is allowed to', () => {
    // A guest holds no JWT, and the projection sits behind get_current_user —
    // so for them every scene would 401. The caller decides; the hook must not
    // fire a request that is known to fail.
    renderHook(() => useWorkspaceObjects('r1', false))
    expect(api.getWorkspaceObjects).not.toHaveBeenCalled()
  })

  it('does not apply a response that was in flight when the room changed', async () => {
    // The real race: r1's request has ALREADY been sent when the room changes.
    // Its response carries no indication it is stale, so without the ticket it
    // would paint the previous room's objects into the new one.
    let resolveFirst: (v: unknown) => void = () => {}
    vi.mocked(api.getWorkspaceObjects)
      .mockReturnValueOnce(new Promise((r) => { resolveFirst = r }) as never)
      .mockResolvedValue({ generated_at: 'x', room_id: 'r2', objects: [object('reading', 'new')] })

    const { result, rerender } = renderHook(
      ({ room }) => useWorkspaceObjects(room, true), { initialProps: { room: 'r1' } },
    )
    // Let r1's request actually leave — the hook defers past a microtask, so
    // without this the r1 effect would bail before calling the API at all and
    // the test would prove nothing about a race.
    await waitFor(() => expect(api.getWorkspaceObjects).toHaveBeenCalledWith('r1'))

    rerender({ room: 'r2' })
    await waitFor(() => expect(result.current.status).toBe('ready'))

    await act(async () => {
      resolveFirst({ generated_at: 'x', room_id: 'r1', objects: [object('reading', 'stale')] })
    })
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.objects.map((o) => o.id)).toEqual(['new'])
  })

  it('never sends a request the room change already superseded', async () => {
    // The cheaper half of the same guard: if the destination changes before the
    // request leaves, it should not leave at all.
    vi.mocked(api.getWorkspaceObjects).mockResolvedValue({
      generated_at: 'x', room_id: 'r2', objects: [],
    })
    const { rerender } = renderHook(
      ({ room }) => useWorkspaceObjects(room, true), { initialProps: { room: 'r1' } },
    )
    rerender({ room: 'r2' })
    await waitFor(() => expect(api.getWorkspaceObjects).toHaveBeenCalled())
    expect(vi.mocked(api.getWorkspaceObjects).mock.calls.flat()).not.toContain('r1')
  })
})
