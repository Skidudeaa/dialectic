import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  __resetMessageDecisionsCacheForTests,
  useMessageDecisions,
} from './useMessageDecisions'
import { api } from '../lib/api.ts'
import type { MessageDecisionExplain } from '../lib/api.ts'

vi.mock('../lib/api.ts', async () => {
  const actual = await vi.importActual<typeof import('../lib/api.ts')>('../lib/api.ts')
  return { ...actual, api: { getThreadDecisions: vi.fn() } }
})

const DECISION: MessageDecisionExplain = {
  reason: 'explicit_mention',
  confidence: 1,
  mode: 'primary',
  use_provoker: false,
  human_turn_count: null,
  semantic_novelty: null,
  unsurfaced_memory_count: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  __resetMessageDecisionsCacheForTests()
})

describe('useMessageDecisions', () => {
  it('starts in loading', () => {
    vi.mocked(api.getThreadDecisions).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useMessageDecisions('r1', 't1', true))
    expect(result.current.status).toBe('loading')
  })

  it('reports ready with the decisions it received', async () => {
    vi.mocked(api.getThreadDecisions).mockResolvedValue({ m1: DECISION })
    const { result } = renderHook(() => useMessageDecisions('r1', 't1', true))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.decisions).toEqual({ m1: DECISION })
  })

  it('reports unavailable when the fetch fails, not empty', async () => {
    vi.mocked(api.getThreadDecisions).mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useMessageDecisions('r1', 't1', true))
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
  })

  it('does not fetch when disabled — a human message has nothing to explain', () => {
    renderHook(() => useMessageDecisions('r1', 't1', false))
    expect(api.getThreadDecisions).not.toHaveBeenCalled()
  })

  it('does not fetch without both a room id and a thread id', () => {
    renderHook(() => useMessageDecisions(null, 't1', true))
    renderHook(() => useMessageDecisions('r1', null, true))
    renderHook(() => useMessageDecisions(undefined, undefined, true))
    expect(api.getThreadDecisions).not.toHaveBeenCalled()
  })

  it('THE POINT: many bubbles in the same thread share exactly ONE request', async () => {
    let resolve: (v: Record<string, MessageDecisionExplain>) => void = () => {}
    vi.mocked(api.getThreadDecisions).mockReturnValue(
      new Promise((r) => { resolve = r }),
    )
    // Five independent "message bubbles" for the same thread — exactly what
    // five MessageBubble instances rendered by one open thread do. None of
    // these renderHook calls awaits anything, so all five mount (and
    // subscribe) before the mocked promise gets a chance to settle.
    const hooks = Array.from({ length: 5 }, () =>
      renderHook(() => useMessageDecisions('r1', 't1', true)),
    )
    expect(api.getThreadDecisions).toHaveBeenCalledTimes(1)
    for (const { result } of hooks) expect(result.current.status).toBe('loading')

    await act(async () => { resolve({ m1: DECISION }) })

    for (const { result } of hooks) {
      expect(result.current).toEqual({ status: 'ready', decisions: { m1: DECISION } })
    }
  })

  it('a bubble mounting after the answer already arrived gets it with no new fetch', async () => {
    vi.mocked(api.getThreadDecisions).mockResolvedValue({ m1: DECISION })
    const first = renderHook(() => useMessageDecisions('r1', 't1', true))
    await waitFor(() => expect(first.result.current.status).toBe('ready'))

    const second = renderHook(() => useMessageDecisions('r1', 't1', true))
    expect(second.result.current).toEqual({ status: 'ready', decisions: { m1: DECISION } })
    expect(api.getThreadDecisions).toHaveBeenCalledTimes(1)
  })

  it('different threads fetch independently and do not cross-contaminate', async () => {
    vi.mocked(api.getThreadDecisions).mockImplementation(async (_room, threadId) => (
      threadId === 't1'
        ? { m1: DECISION } as Record<string, MessageDecisionExplain>
        : { m2: DECISION } as Record<string, MessageDecisionExplain>
    ))
    const a = renderHook(() => useMessageDecisions('r1', 't1', true))
    const b = renderHook(() => useMessageDecisions('r1', 't2', true))
    await waitFor(() => expect(a.result.current.status).toBe('ready'))
    await waitFor(() => expect(b.result.current.status).toBe('ready'))
    expect(api.getThreadDecisions).toHaveBeenCalledTimes(2)
    if (a.result.current.status !== 'ready' || b.result.current.status !== 'ready') {
      throw new Error('unreachable')
    }
    expect(Object.keys(a.result.current.decisions)).toEqual(['m1'])
    expect(Object.keys(b.result.current.decisions)).toEqual(['m2'])
  })

  it('one bubble unmounting does not cancel the fetch for the others', async () => {
    vi.mocked(api.getThreadDecisions).mockResolvedValue({ m1: DECISION })
    const a = renderHook(() => useMessageDecisions('r1', 't1', true))
    const b = renderHook(() => useMessageDecisions('r1', 't1', true))
    a.unmount()
    await waitFor(() => expect(b.result.current.status).toBe('ready'))
  })
})
