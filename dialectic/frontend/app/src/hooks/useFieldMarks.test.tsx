import { renderHook, waitFor, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useFieldMarks } from './useFieldMarks'
import { api } from '../lib/api.ts'
import type { FieldMark } from '../types/workspace.ts'

vi.mock('../lib/api.ts', () => ({
  api: { getFieldMarks: vi.fn() },
}))

/**
 * Copied wholesale from useWorkspaceObjects.test.tsx -- same three states,
 * same race, same reasons. See that file's header comment for why the
 * distinction between "empty" and "unavailable" has to exist in the type.
 */

const mark = (id: string, relation: FieldMark['relation'] = 'emerging_position'): FieldMark => ({
  id: `field_mark:${id}`,
  room_id: 'r1',
  thread_id: null,
  relation,
  origin: 'inferred',
  review: 'provisional',
  deliberative_status: 'active',
  subjects: [],
  title: `mark ${id}`,
  payload: {},
  supersedes_id: null,
  caused_by_id: null,
  actor_user_id: null,
  provenance: 'field_inference',
  created_at: '2026-08-13T10:00:00Z',
  reviews: [],
})

describe('useFieldMarks', () => {
  beforeEach(() => vi.clearAllMocks())

  it('starts in loading, never in empty', () => {
    vi.mocked(api.getFieldMarks).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useFieldMarks('r1', true))
    // An in-flight fetch that reports "nothing here" is the exact lie §7.5
    // forbids, and it is the state a surface spends most of its life in for
    // a Field the inference job has not populated yet.
    expect(result.current.status).toBe('loading')
  })

  it('reports ready with the marks it received', async () => {
    vi.mocked(api.getFieldMarks).mockResolvedValue({
      generated_at: '2026-08-13T10:00:00Z',
      room_id: 'r1',
      marks: [mark('a'), mark('b', 'unanswered_question')],
    })
    const { result } = renderHook(() => useFieldMarks('r1', true))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.marks).toHaveLength(2)
  })

  it('distinguishes a genuinely empty Field from a failure', async () => {
    vi.mocked(api.getFieldMarks).mockResolvedValue({
      generated_at: '2026-08-13T10:00:00Z', room_id: 'r1', marks: [],
    })
    const { result } = renderHook(() => useFieldMarks('r1', true))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.marks).toEqual([])
  })

  it('reports unavailable when the projection fails, not empty', async () => {
    vi.mocked(api.getFieldMarks).mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useFieldMarks('r1', true))
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
  })

  it('can retry a failure', async () => {
    vi.mocked(api.getFieldMarks).mockRejectedValueOnce(new Error('boom'))
    vi.mocked(api.getFieldMarks).mockResolvedValue({
      generated_at: 'x', room_id: 'r1', marks: [mark('a')],
    })
    const { result } = renderHook(() => useFieldMarks('r1', true))
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
    if (result.current.status !== 'unavailable') throw new Error('unreachable')
    // Captured OUTSIDE act: TypeScript's narrowing does not survive into the
    // closure, and re-reading result.current there is the union again.
    const { retry } = result.current
    await act(async () => { retry() })
    await waitFor(() => expect(result.current.status).toBe('ready'))
  })

  it('exposes refresh() on the ready state, for after a review POST', async () => {
    vi.mocked(api.getFieldMarks)
      .mockResolvedValueOnce({ generated_at: 'x', room_id: 'r1', marks: [mark('a')] })
      .mockResolvedValue({ generated_at: 'y', room_id: 'r1', marks: [mark('a'), mark('b')] })
    const { result } = renderHook(() => useFieldMarks('r1', true))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.marks).toHaveLength(1)
    const { refresh } = result.current
    await act(async () => { refresh() })
    await waitFor(() => {
      if (result.current.status !== 'ready') throw new Error('unreachable')
      expect(result.current.marks).toHaveLength(2)
    })
  })

  it('does not fetch until it is allowed to', () => {
    // A guest holds no JWT, and the projection sits behind get_current_user —
    // so for them the Field would 401. The caller decides; the hook must not
    // fire a request that is known to fail.
    renderHook(() => useFieldMarks('r1', false))
    expect(api.getFieldMarks).not.toHaveBeenCalled()
  })

  it('does not apply a response that was in flight when the room changed', async () => {
    // The real race: r1's request has ALREADY been sent when the room
    // changes. Its response carries no indication it is stale, so without
    // the ticket it would paint the previous room's marks into the new one.
    let resolveFirst: (v: unknown) => void = () => {}
    vi.mocked(api.getFieldMarks)
      .mockReturnValueOnce(new Promise((r) => { resolveFirst = r }) as never)
      .mockResolvedValue({ generated_at: 'x', room_id: 'r2', marks: [mark('new')] })

    const { result, rerender } = renderHook(
      ({ room }) => useFieldMarks(room, true), { initialProps: { room: 'r1' } },
    )
    // Let r1's request actually leave — the hook defers past a microtask, so
    // without this the r1 effect would bail before calling the API at all
    // and the test would prove nothing about a race.
    await waitFor(() => expect(api.getFieldMarks).toHaveBeenCalledWith('r1'))

    rerender({ room: 'r2' })
    await waitFor(() => expect(result.current.status).toBe('ready'))

    await act(async () => {
      resolveFirst({ generated_at: 'x', room_id: 'r1', marks: [mark('stale')] })
    })
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.marks.map((m) => m.id)).toEqual(['field_mark:new'])
  })

  it('never sends a request the room change already superseded', async () => {
    // The cheaper half of the same guard: if the destination changes before
    // the request leaves, it should not leave at all.
    vi.mocked(api.getFieldMarks).mockResolvedValue({
      generated_at: 'x', room_id: 'r2', marks: [],
    })
    const { rerender } = renderHook(
      ({ room }) => useFieldMarks(room, true), { initialProps: { room: 'r1' } },
    )
    rerender({ room: 'r2' })
    await waitFor(() => expect(api.getFieldMarks).toHaveBeenCalled())
    expect(vi.mocked(api.getFieldMarks).mock.calls.flat()).not.toContain('r1')
  })
})
