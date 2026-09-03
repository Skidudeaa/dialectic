import { describe, expect, it } from 'vitest'
import type { Message } from '../../../types'
import { humanWordsByNode, refFocusId, toSurfaceMessages } from './surfaceModel'

const base = (over: Partial<Message>): Message => ({
  id: 'm', thread_id: 't', sequence: 1, created_at: '2026-09-02T12:00:00Z',
  speaker_type: 'human', user_id: 'amo', message_type: 'text', content: 'x', ...over,
})

describe('toSurfaceMessages', () => {
  it('resolves author, anchor, refs, parent and newness from the raw message', () => {
    const msgs = [
      base({ id: 'a', created_at: '2026-09-02T10:00:00Z', metadata: { anchor: { kind: 'node', id: 'n1', label: 'Hormuz Closure' } } }),
      base({
        id: 'b', speaker_type: 'llm_primary', user_id: null, created_at: '2026-09-02T11:00:00Z',
        references_message_id: 'a',
        metadata: {
          refs: [{ entity: 'reading_items', id: 'r1', label: 'FT' }, { entity: 'reading_items', id: 'r1', label: 'dup' }],
          tools: { iterations: 1, degraded: false, calls: [{ name: 'search_reading', label: 'searching', ok: true }] },
        },
      }),
      base({ id: 'c', user_id: 'dan', created_at: '2026-09-02T12:00:00Z', references_message_id: 'missing' }),
    ]
    const out = toSurfaceMessages(msgs, {
      userNames: { amo: 'Amo', dan: 'Dan' }, currentUserId: 'amo', unreadSince: '2026-09-02T10:30:00Z',
    })
    expect(out[0].author).toMatchObject({ name: 'Amo', kind: 'human', isSelf: true, glyph: 'A' })
    expect(out[0].anchor?.label).toBe('Hormuz Closure')
    expect(out[0].topic).toBe('Hormuz Closure')
    expect(out[0].isNew).toBe(false)
    expect(out[1].author).toMatchObject({ kind: 'machine', role: 'primary' })
    expect(out[1].refs).toEqual([{ entity: 'reading_items', id: 'r1', label: 'FT' }])
    expect(out[1].parentId).toBe('a')
    expect(out[1].tools).toEqual([{ name: 'search_reading', label: 'searching', ok: true }])
    expect(out[1].isNew).toBe(true)
    expect(out[1].topic).toBe('the whole room')
    // A parent outside the window is no parent at all.
    expect(out[2].parentId).toBeNull()
    expect(out[2].author.name).toBe('Dan')
  })
})

describe('humanWordsByNode', () => {
  it('keeps the latest HUMAN word per node and ignores the machine', () => {
    const msgs = toSurfaceMessages([
      base({ id: 'a', created_at: '2026-09-01T10:00:00Z', content: 'first', metadata: { anchor: { kind: 'node', id: 'n1', label: 'N1' } } }),
      base({ id: 'b', created_at: '2026-09-02T10:00:00Z', content: 'latest', user_id: 'dan', metadata: { anchor: { kind: 'node', id: 'n1', label: 'N1' } } }),
      base({ id: 'c', created_at: '2026-09-03T10:00:00Z', content: 'machine', speaker_type: 'llm_primary', user_id: null, metadata: { anchor: { kind: 'node', id: 'n1', label: 'N1' } } }),
      base({ id: 'd', created_at: '2026-09-03T10:00:00Z', content: 'edge talk', metadata: { anchor: { kind: 'edge', id: 'a->b', label: 'A → B' } } }),
    ], { userNames: { amo: 'Amo', dan: 'Dan' }, currentUserId: 'amo' })
    const words = humanWordsByNode(msgs)
    expect(Object.keys(words)).toEqual(['n1'])
    expect(words.n1).toMatchObject({ authorName: 'Dan', quote: 'latest' })
  })
})

describe('refFocusId', () => {
  it('maps row kinds Focus can open and refuses the rest', () => {
    expect(refFocusId({ entity: 'reading_items', id: 'r', label: '' })).toBe('reading:r')
    expect(refFocusId({ entity: 'field_marks', id: 'f', label: '' })).toBe('field_mark:f')
    expect(refFocusId({ entity: 'geo_scopes', id: 'g', label: '' })).toBe('geo_scope:g')
    expect(refFocusId({ entity: 'world_observations', id: 'o', label: '' })).toBeNull()
    expect(refFocusId({ entity: 'thesis_node', id: 'n', label: '' })).toBeNull()
  })
})
