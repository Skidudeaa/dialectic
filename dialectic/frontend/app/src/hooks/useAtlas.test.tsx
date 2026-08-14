import { renderHook, waitFor, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAtlas } from './useAtlas'
import type { AtlasProjection } from '../types/atlas.ts'

/**
 * Same three-state contract as useWorkspaceObjects (design v2 §7.5): an
 * in-flight or failed fetch must never read as "the atlas holds nothing."
 *
 * WHY window.fetch is mocked directly rather than lib/api.ts: useAtlas's
 * fetch is deliberately INLINE (see the hook's own docstring) — it is not
 * routed through DialecticAPI yet, so there is no api.getAtlas to mock.
 */

const projection = (nodeIds: string[]): AtlasProjection => ({
  generated_at: '2026-08-13T10:00:00Z',
  nodes: nodeIds.map((id) => ({
    id, kind: 'reading', room_id: 'r1', branch_id: null,
    title: id, summary: '', status: '', due: false,
    created_at: '2026-08-13T10:00:00Z', updated_at: '2026-08-13T10:00:00Z',
  })),
  edges: [],
})

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok, status,
    json: async () => body,
  } as Response
}

describe('useAtlas', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('starts in loading, never in empty', () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useAtlas(true))
    expect(result.current.status).toBe('loading')
  })

  it('reports ready with the projection it received', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(projection(['reading:a', 'reading:b'])))
    const { result } = renderHook(() => useAtlas(true))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.projection.nodes).toHaveLength(2)
  })

  it('distinguishes a genuinely empty atlas from a failure', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(projection([])))
    const { result } = renderHook(() => useAtlas(true))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    if (result.current.status !== 'ready') throw new Error('unreachable')
    expect(result.current.projection.nodes).toEqual([])
  })

  it('reports unavailable on a non-2xx response, not empty', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'nope' }, false, 401))
    const { result } = renderHook(() => useAtlas(true))
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
  })

  it('reports unavailable on a network failure', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('network down'))
    const { result } = renderHook(() => useAtlas(true))
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
  })

  it('can retry a failure', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ detail: 'nope' }, false, 500))
      .mockResolvedValue(jsonResponse(projection(['reading:a'])))
    const { result } = renderHook(() => useAtlas(true))
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
    if (result.current.status !== 'unavailable') throw new Error('unreachable')
    const { retry } = result.current
    await act(async () => { retry() })
    await waitFor(() => expect(result.current.status).toBe('ready'))
  })

  it('does not fetch until it is allowed to', () => {
    // A guest holds no JWT, and /users/me/atlas sits behind get_current_user
    // — every call would 401. The caller decides; the hook must not fire a
    // request known to fail.
    renderHook(() => useAtlas(false))
    expect(fetch).not.toHaveBeenCalled()
  })

  it('fetches /users/me/atlas with no room-token header', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(projection([])))
    renderHook(() => useAtlas(true))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const [url, options] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/users/me/atlas')
    expect((options?.headers as Record<string, string>)['X-Room-Token']).toBeUndefined()
  })

  it('does not send a second request on an unrelated re-render', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(projection([])))
    const { rerender } = renderHook(
      ({ enabled }) => useAtlas(enabled), { initialProps: { enabled: true } },
    )
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    rerender({ enabled: true })
    // enabled did not change identity in a way the effect depends on
    // differently, and no retry was requested -- still exactly one call.
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
