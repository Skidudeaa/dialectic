import { describe, expect, it, vi } from 'vitest'
import { api } from './api.ts'
import {
  WORKSPACE_ACTIONS,
  WORKSPACE_OBJECT_KINDS,
  WORKSPACE_ORIGINS,
  WORKSPACE_REVIEW_STATES,
} from '../types/workspace.ts'

/**
 * The client half of the workspace-object contract (design v2 §8.1).
 *
 * The two SHAPES are pinned against the backend model by a real test on the
 * Python side (dialectic/tests/test_workspace_contract.py, which reads
 * types/workspace.ts). What can only be checked here is the call itself: the
 * path the client actually requests, and the fact that it never writes.
 */

const PROJECTION = {
  generated_at: '2026-08-12T12:00:00+00:00',
  room_id: 'aaaaaaaa-0000-4000-8000-000000000001',
  objects: [],
}

function stubFetch() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => PROJECTION,
  })
  vi.stubGlobal('fetch', fetchMock)
  window.fetch = fetchMock as unknown as typeof window.fetch
  return fetchMock
}

describe('getWorkspaceObjects', () => {
  const roomId = 'aaaaaaaa-0000-4000-8000-000000000001'

  it('requests the room projection endpoint', async () => {
    const fetchMock = stubFetch()
    await expect(api.getWorkspaceObjects(roomId)).resolves.toEqual(PROJECTION)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/rooms/${roomId}/workspace/objects`,
    )
  })

  it('reads, never writes', () => {
    // Release 1 adapters project and nothing else; a surface that acts on an
    // object calls that entity's own endpoint. A method that started POSTing
    // here would be a second write path for entities that already have one.
    const fetchMock = stubFetch()
    return api.getWorkspaceObjects(roomId).then(() => {
      const init = fetchMock.mock.calls[0][1] ?? {}
      expect(init.method ?? 'GET').toBe('GET')
      expect(init.body).toBeUndefined()
    })
  })

  it('passes a kind filter through as an encoded query', async () => {
    const fetchMock = stubFetch()
    await api.getWorkspaceObjects(roomId, 'research_brief')
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/rooms/${roomId}/workspace/objects?kind=research_brief`,
    )
  })
})

describe('the closed vocabularies', () => {
  it('name every adapter in the spec list', () => {
    expect([...WORKSPACE_OBJECT_KINDS]).toEqual([
      'reading', 'research_brief', 'thesis', 'commitment', 'proposal',
      'dossier_entry', 'house_movement', 'record_event', 'field_mark',
    ])
  })

  it('keep failed reachable, so a failed write can never be invisible', () => {
    // §5.1 and §8.4: a human-authorized write that did not complete must stay
    // on screen. Dropping it from the vocabulary is how it becomes silent.
    expect(WORKSPACE_REVIEW_STATES).toContain('failed')
  })

  it('separate what a surface may offer from who produced the row', () => {
    expect(WORKSPACE_ACTIONS).toContain('accept')
    expect(WORKSPACE_ORIGINS).toEqual(['human', 'dialectic', 'desk', 'system'])
  })
})
