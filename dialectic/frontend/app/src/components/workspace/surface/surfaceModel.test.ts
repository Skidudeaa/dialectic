import { describe, expect, it } from 'vitest'
import type { Message } from '../../../types'
import { discussionMap, focusDiscussionMap, searchDiscussionMap, passageKey, discussionThreads, humanWordsByNode, refFocusId, toSurfaceMessages } from './surfaceModel'

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
    expect(out[1].topic).toBe('FT')
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

describe('passage discussion grouping', () => {
  it('groups the same quotation and revision while keeping real replies, other sources, and orphans', () => {
    const ref = { entity: 'reading_items' as const, id: 'article', label: 'Article', quote: 'A precise claim', content_sha256: 'a'.repeat(64) }
    const rows = [
      base({ id: 'one', metadata: { refs: [ref] } }),
      base({ id: 'two', metadata: { refs: [{ ...ref, quote: 'A   precise claim' }] } }),
      base({ id: 'reply', references_message_id: 'one', metadata: { refs: [{ ...ref, id: 'other' }] } }),
      base({ id: 'different', metadata: { refs: [{ ...ref, quote: 'Another passage' }] } }),
      base({ id: 'revised', metadata: { refs: [{ ...ref, content_sha256: 'b'.repeat(64) }] } }),
      base({ id: 'other', metadata: { refs: [{ ...ref, id: 'other' }] } }),
      base({ id: 'orphan', references_message_id: 'outside-window' }),
    ]
    const groups = discussionThreads(toSurfaceMessages(rows, { userNames: {}, currentUserId: null }))
    expect(groups).toHaveLength(5)
    expect(groups[0].roots.map((m) => m.id)).toEqual(['one', 'two'])
    expect(groups[0].messages.map((m) => m.id)).toEqual(['one', 'two', 'reply'])
    expect(groups[4].messages[0].message.references_message_id).toBe('outside-window')
  })
})


describe('discussion map topology and search', () => {
  const article = { entity: 'reading_items' as const, id: 'article', label: 'An Alien Mind', quote: 'A repeated observation.', content_sha256: 'a'.repeat(64), quote_occurrence: 1 }
  const study = { entity: 'reading_items' as const, id: 'study', label: 'Timing study', quote: 'Measure the delay before judging intent.', content_sha256: 'b'.repeat(64) }
  function fixture() {
    const messages = toSurfaceMessages([
      base({ id: 'root', content: 'An experience from my clinic.', metadata: { refs: [article] } }),
      base({ id: 'child', user_id: 'dan', content: 'The delay matters more than the conclusion.', references_message_id: 'root', metadata: { refs: [study] } }),
      base({ id: 'grandchild', content: 'What would distinguish these explanations?', references_message_id: 'child' }),
      base({ id: 'sibling', content: 'A separate reply.', references_message_id: 'root' }),
      base({ id: 'other', user_id: 'dan', content: 'An unrelated branch.', metadata: { refs: [{ ...article, quote_occurrence: 0 }] } }),
      base({ id: 'machine', speaker_type: 'llm_primary', content: 'A machine contribution.', user_id: null }),
    ], { userNames: { amo: 'Amo', dan: 'Dan' }, currentUserId: 'amo' })
    return discussionMap(discussionThreads(messages), article)
  }

  it('searches actual people, words and full cited passages while preserving repeated passage identity', () => {
    const graph = fixture()
    expect(searchDiscussionMap(graph, 'DAN delay').map((node) => node.id)).toEqual(['child'])
    expect(searchDiscussionMap(graph, 'clinic').map((node) => node.id)).toEqual(['root'])
    expect(searchDiscussionMap(graph, 'Timing study').map((node) => node.id)).toEqual(expect.arrayContaining(['source:study', 'child']))
    expect(searchDiscussionMap(graph, 'before judging intent').map((node) => node.id)).toEqual(expect.arrayContaining(['child', `passage:${passageKey(study)}`]))
    expect(searchDiscussionMap(graph, 'something nobody said')).toEqual([])
    expect(searchDiscussionMap(graph, '   ')).toEqual([])
    const occurrences = graph.nodes.filter((node) => node.kind === 'passage' && node.ref?.id === article.id)
    expect(occurrences.map((node) => node.ref?.quote_occurrence)).toEqual([1, 0])
    expect(new Set(occurrences.map((node) => node.id)).size).toBe(2)
    expect(new Set(graph.edges.map((edge) => edge.kind))).toEqual(new Set(['contains', 'discusses', 'cites', 'reply']))
  })

  it('focuses the exact actual ancestor path and its sources without siblings or invented semantic edges', () => {
    const graph = fixture()
    const focused = focusDiscussionMap(graph, 'grandchild', new Set(['root']))
    expect(focused.nodes.filter((node) => node.kind === 'thought').map((node) => node.id)).toEqual(['root', 'child', 'grandchild'])
    expect(focused.nodes.filter((node) => node.kind === 'source').map((node) => node.id)).toEqual(['source:article', 'source:study'])
    expect(focused.nodes.filter((node) => node.kind === 'passage').map((node) => node.ref)).toEqual([article, study])
    expect(focused.edges.filter((edge) => edge.kind === 'reply')).toEqual([{ from: 'root', to: 'child', kind: 'reply' }, { from: 'child', to: 'grandchild', kind: 'reply' }])
    const passage = focusDiscussionMap(graph, `passage:${passageKey(study)}`, new Set())
    expect(passage.nodes.filter((node) => node.kind === 'thought').map((node) => node.id)).toEqual(['root', 'child'])
  })

  it('collapses real descendants and their unused passages, and restores the entire graph', () => {
    const graph = fixture()
    const collapsed = focusDiscussionMap(graph, null, new Set(['root']))
    expect(collapsed.nodes.filter((node) => node.kind === 'thought').map((node) => node.id)).toEqual(['root', 'other', 'machine'])
    expect(collapsed.nodes.find((node) => node.id === `passage:${passageKey(study)}`)).toBeUndefined()
    expect(focusDiscussionMap(graph, null, new Set())).toEqual(graph)
  })
})
