import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useRef, useState } from 'react'
import type { MessageAnchor, MessageRef } from '../../../../types'
import { discussionThreads, WHOLE_ROOM_TOPIC, type DailyActivity, type SurfaceAuthor, type SurfaceMsg } from '../surfaceModel'
import { SurfaceMessage } from './SurfaceMessage'
import { ShapeStream } from './ShapeStream'
import { ShapeDiscussion } from './ShapeDiscussion'
import { ShapeTree } from './ShapeTree'
import { ShapeLanes } from './ShapeLanes'
import { ShapeSignal } from './ShapeSignal'
import { SurfaceConversation } from '../SurfaceConversation'
import type { ConversationShape } from '../surfaceModel'
import type { MessageInputHandle } from '../../../chat/MessageInput'
import { api } from '../../../../lib/api'
import { useAppStore } from '../../../../stores/appStore'

function human(id: string, name: string): SurfaceAuthor {
  return { id, name, kind: 'human', glyph: name.charAt(0).toUpperCase(), isSelf: false }
}

function machine(role?: 'primary' | 'provoker' | 'annotator'): SurfaceAuthor {
  return { id: 'dialectic', name: 'Dialectic', kind: 'machine', glyph: ')', role, isSelf: false }
}

let seq = 0
function msg(overrides: Partial<SurfaceMsg> & { author: SurfaceAuthor }): SurfaceMsg {
  seq += 1
  return {
    id: overrides.id ?? `m${seq}`,
    author: overrides.author,
    createdAt: overrides.createdAt ?? '2026-09-01T10:00:00Z',
    time: overrides.time ?? '10:00',
    text: overrides.text ?? 'hello',
    anchor: overrides.anchor ?? null,
    refs: overrides.refs ?? [],
    parentId: overrides.parentId ?? null,
    tools: overrides.tools ?? [],
    isNew: overrides.isNew ?? false,
    isStreaming: overrides.isStreaming ?? false,
    topic: overrides.topic ?? WHOLE_ROOM_TOPIC,
    message: overrides.message ?? {
      id: overrides.id ?? `m${seq}`, thread_id: 'thread', sequence: seq,
      created_at: overrides.createdAt ?? '2026-09-01T10:00:00Z',
      speaker_type: overrides.author.kind === 'human' ? 'human' : 'llm_primary',
      user_id: overrides.author.kind === 'human' ? overrides.author.id : null,
      user_name: overrides.author.name,
      content: overrides.text ?? 'hello', message_type: 'text',
      references_message_id: overrides.parentId,
      metadata: { ...(overrides.anchor ? { anchor: overrides.anchor } : {}), refs: overrides.refs },
    },
  }
}

describe('SurfaceMessage', () => {
  it('renders the author name', () => {
    render(<SurfaceMessage msg={msg({ author: human('u1', 'Amo'), text: 'hi there' })} />)
    expect(screen.getByText('Amo')).toBeInTheDocument()
  })

  it('calls onAnchor with the anchor when the anchor chip is tapped', () => {
    const onAnchor = vi.fn()
    const anchor: MessageAnchor = { kind: 'node', id: 'n1', label: 'Cascade phase' }
    render(<SurfaceMessage msg={msg({ author: human('u1', 'Amo'), anchor })} onAnchor={onAnchor} />)
    fireEvent.click(screen.getByRole('button', { name: /ON Cascade phase/ }))
    expect(onAnchor).toHaveBeenCalledWith(anchor)
  })

  it('calls onOpenRef with the ref when a ref chip is tapped', () => {
    const onOpenRef = vi.fn()
    const ref: MessageRef = { entity: 'reading_items', id: 'r1', label: 'GDELT wire hit' }
    render(<SurfaceMessage msg={msg({ author: human('u1', 'Amo'), refs: [ref] })} onOpenRef={onOpenRef} />)
    fireEvent.click(screen.getByRole('button', { name: /GDELT wire hit/ }))
    expect(onOpenRef).toHaveBeenCalledWith(ref)
  })
})

describe('ShapeStream', () => {
  it('keeps a Round actionable on the default Surface', async () => {
    const previousRoom = useAppStore.getState().currentRoom
    useAppStore.setState({ currentRoom: { id: 'room', name: 'Room', token: 'token', is_home: false } })
    const state = { message_id: 'round', peers: [], questions: [{
      commitment_id: 'q', claim: 'Will shipping resume by Friday?', closes: '2099-09-10', status: 'active',
      resolution: null, my_forecast: null, my_peer_forecast: null, my_revisions: 0,
      house_committed: false, revealed: false, waiting_on_other: false,
    }] }
    vi.spyOn(api, 'readRound').mockResolvedValue(state)
    const forecast = vi.spyOn(api, 'recordForecast').mockResolvedValue(state)
    const round = msg({ id: 'round', author: machine(), text: 'The Round' })
    round.message.metadata = { question_round: { opened: '2026-09-05', questions: [] } }
    try {
      render(<ShapeStream messages={[round]} onOpenRef={vi.fn()} />)
      await screen.findByText('Will shipping resume by Friday?')
      fireEvent.change(screen.getByRole('slider', { name: 'you' }), { target: { value: '0.7' } })
      fireEvent.click(screen.getByRole('button', { name: 'lock in' }))
      await waitFor(() => expect(forecast).toHaveBeenCalledWith('room', 'q', 0.7, undefined, null))
    } finally {
      act(() => useAppStore.setState({ currentRoom: previousRoom }))
    }
  })

  it('renders every message', () => {
    const messages = [
      msg({ id: 'm1', author: human('u1', 'Amo'), text: 'first' }),
      msg({ id: 'm2', author: machine('primary'), text: 'second' }),
    ]
    render(<ShapeStream messages={messages} onOpenRef={vi.fn()} />)
    expect(screen.getByText('first')).toBeInTheDocument()
    expect(screen.getByText('second')).toBeInTheDocument()
  })

  it('keeps the source inspector available beside a conversation without viewport-dependent links', () => {
    const messages = [
      msg({ author: human('u1', 'Amo'), refs: [{ entity: 'memories', id: 'x1', label: 'a memory' }] }),
    ]
    render(<ShapeStream messages={messages} context={<aside>Choose a reading</aside>} onOpenRef={vi.fn()} />)
    expect(screen.getByText('Choose a reading')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /a memory/ })).toBeEnabled()
  })
})

describe('ShapeTree', () => {
  it('nests a reply under its parent', () => {
    const root = msg({ id: 'root1', author: human('u1', 'Amo'), text: 'the claim' })
    const reply = msg({ id: 'reply1', author: machine('primary'), text: 'a reply', parentId: 'root1' })
    render(<ShapeTree messages={[root, reply]} onOpenRef={vi.fn()} />)
    const rootNode = screen.getByText('the claim').closest('.surf-tree-node')!
    const replyArticle = screen.getByText('a reply').closest('article')!
    expect(rootNode.contains(replyArticle)).toBe(true)
  })

  it('lists a merge candidate for a ref shared by two root trees', () => {
    const sharedRef: MessageRef = { entity: 'field_marks', id: 'fm1', label: 'confluence trigger' }
    const rootA = msg({ id: 'a', author: human('u1', 'Amo'), text: 'root A', refs: [sharedRef] })
    const rootB = msg({ id: 'b', author: human('u2', 'Dan'), text: 'root B', refs: [sharedRef] })
    render(<ShapeTree messages={[rootA, rootB]} onOpenRef={vi.fn()} />)
    expect(screen.getByText(/MERGE CANDIDATES/)).toBeInTheDocument()
    expect(screen.getByText(/confluence trigger — 2 trees/)).toBeInTheDocument()
  })
})

describe('ShapeLanes', () => {
  it('puts a machine message in the machine column and names whose move', () => {
    const amo = human('u1', 'Amo')
    const machineMsg = msg({ author: machine('primary'), text: 'machine says' })
    render(<ShapeLanes messages={[machineMsg]} humans={[amo]} onOpenRef={vi.fn()} />)
    const cell = screen.getByText('machine says').closest('.surf-lane-cell')!
    expect(cell.querySelector('.surf-lane-cell-author')?.textContent).toBe('Dialectic')
    // Amo has said nothing in this band, so it reads as his move.
    expect(screen.getByText(/move: Amo/)).toBeInTheDocument()
  })
})

describe('ShapeSignal', () => {
  it('renders the ratio line from rows and the two state lines', () => {
    const activity: DailyActivity = {
      days: 2,
      rows: [
        { day: '2026-09-01', human: 5, llm_primary: 2, llm_provoker: 1, llm_annotator: 0, system: 0 },
        { day: '2026-09-02', human: 3, llm_primary: 1, llm_provoker: 0, llm_annotator: 1, system: 0 },
      ],
    }
    render(
      <ShapeSignal activity={activity} status="ready" annotatorEnabled={false} addressedOnly={true} />,
    )
    // human total 8, machine total (3+1+1)=5 -> 0.6 : 1
    expect(screen.getByText('machine : human = 0.6 : 1')).toBeInTheDocument()
    expect(screen.getByText('Annotator silent · writes marks only')).toBeInTheDocument()
    expect(screen.getByText('Dialectic speaks when addressed or a gate fires')).toBeInTheDocument()
  })
})

describe('conversation shape navigation', () => {
  it.each(['Tree', 'Lanes'])('leaves Sources mode for %s and keeps the draft and reply', async (shape) => {
    vi.spyOn(api, 'getReadingLibrary').mockResolvedValue({ items: [], next_before: null })
    const message = msg({ author: human('u1', 'Amo'), text: 'A thought to reply to' })
    const noop = () => undefined
    function Conversation() {
      const [shape, setShape] = useState<ConversationShape>('stream')
      const [evidenceOpen, setEvidenceOpen] = useState(false)
      const composerRef = useRef<MessageInputHandle>(null)
      return <SurfaceConversation
        roomId="room" messages={[message]} humans={[message.author]}
        shape={shape} onShape={setShape} evidenceOpen={evidenceOpen} onEvidenceOpen={setEvidenceOpen}
        wide onToggleWide={noop} anchor={null} onAnchor={noop} onClearAnchor={noop}
        pendingRefs={[]} onRemovePendingRef={noop} onClearPendingRefs={noop}
        composerRef={composerRef} typingUsers={[]} activityLabel={null}
        onOpenRef={noop} onFork={noop} annotatorEnabled={false} addressedOnly
        selectedEvidence={null} onSelectEvidence={noop} onStageRef={noop} onOpenFull={noop}
        controls={{ messages: [message.message], currentUserId: 'u2', userNames: { u1: 'Amo' } }}
        composer={{ draft: 'An unfinished reply', disabled: false, memberNames: ['Amo', 'Dan'],
          send: () => false, onTypingStart: noop, onTypingStop: noop, onTypingContent: noop }}
      />
    }
    const { container } = render(<Conversation />)
    await waitFor(() => expect(api.getReadingLibrary).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bring a source' }))
    expect(screen.getByRole('region', { name: 'Conversation' })).toHaveClass('surf-conv--evidence-open')
    fireEvent.click(screen.getByText('More', { selector: 'summary' }))
    fireEvent.click(screen.getByRole('button', { name: shape }))
    expect(screen.getByRole('button', { name: 'Bring a source' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('region', { name: 'Conversation' })).not.toHaveClass('surf-conv--evidence-open')
    expect(container.querySelector('.surf-evidence')).toBeNull()
    expect(container.querySelector('textarea')).toHaveValue('An unfinished reply')
    expect(container.querySelector('.reply-preview-bar')).toHaveTextContent('A thought to reply to')
  })
})

describe('passage threads and map', () => {
  it('renders shared context once, collapses replies, and retains actions and map navigation', () => {
    const ref: MessageRef = { entity: 'reading_items', id: 'reading', label: 'Article', quote: 'An exact passage' }
    const parent = msg({ id: 'parent', author: human('u1', 'Amo'), text: 'A claim to test', refs: [ref] })
    const child = msg({ id: 'child', author: human('u2', 'Dan'), text: 'The reply tests it', refs: [{ ...ref, quote_occurrence: 0 }], parentId: parent.id })
    const threads = discussionThreads([parent, child])
    const reply = vi.fn(), select = vi.fn(), jump = vi.fn()
    const props = { threads, controls: { messages: [parent.message, child.message], currentUserId: 'u1', onFork: vi.fn() }, selected: ref, active: threads[0].id, jump: null,
      onSelect: select, onOpenRef: vi.fn(), onReply: reply, onJump: jump }
    const { container, rerender } = render(<ShapeDiscussion {...props} map={false} />)
    expect(screen.getAllByText('An exact passage')).toHaveLength(1)
    expect(container.querySelector('.msg-quote')).toBeNull()
    expect(container.querySelector('.msg-evidence-source')).toBeNull()
    fireEvent.click(screen.getAllByRole('button', { name: 'Reply' })[1])
    expect(reply).toHaveBeenCalledWith(child.id)
    fireEvent.click(screen.getByRole('button', { name: /1 reply to Amo/ }))
    expect(screen.queryByText(child.text)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Read in source/ }))
    expect(select).toHaveBeenCalledWith(threads[0])
    fireEvent.click(screen.getByLabelText('More actions for Amo’s contribution'))
    expect(screen.getByRole('button', { name: 'Fork' })).toBeVisible()
    rerender(<ShapeDiscussion {...props} map />)
    expect(container.querySelectorAll('svg path')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: /^Dan.*The reply tests it$/ }))
    expect(jump).toHaveBeenCalledWith(child.id)
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in map' }))
    expect(screen.getByRole('button', { name: 'Reset map zoom' })).toHaveTextContent('110%')
  })
})


describe('accepted comments and branch continuity', () => {
  it('waits for the accepted target, opens its collapsed parent, and reveals it only once', async () => {
    const parent = msg({ id: 'receipt-parent', author: human('u1', 'Amo') })
    const earlier = msg({ id: 'earlier-child', author: human('u2', 'Dan'), parentId: parent.id })
    const accepted = msg({ id: 'accepted-child', author: human('u1', 'Amo'), parentId: parent.id })
    const props = { controls: { messages: [], currentUserId: 'u1' }, selected: null, active: null, map: false, onSelect: vi.fn(), onOpenRef: vi.fn(), onReply: vi.fn(), onJump: vi.fn() }
    const { container, rerender } = render(<ShapeDiscussion {...props} threads={discussionThreads([parent, earlier])} jump={null} />)
    fireEvent.click(screen.getByRole('button', { name: /1 reply to Amo/ }))
    const jump = { id: accepted.id, nonce: 17 }
    rerender(<ShapeDiscussion {...props} threads={discussionThreads([parent, earlier])} jump={jump} />)
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)) })
    expect(container.querySelector('[data-mid="earlier-child"]')).toBeNull()
    rerender(<ShapeDiscussion {...props} threads={discussionThreads([parent, earlier, accepted])} jump={jump} />)
    await waitFor(() => expect(container.querySelector('[data-mid="accepted-child"]')).not.toBeNull())
    const pane = container.querySelector<HTMLElement>('.surf-discussion')!
    await waitFor(() => expect(pane.scrollTop).toBe(-90))
    pane.scrollTop = 123
    const peer = msg({ author: human('u2', 'Dan'), parentId: parent.id })
    rerender(<ShapeDiscussion {...props} threads={discussionThreads([parent, earlier, accepted, peer])} jump={jump} />)
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)) })
    expect(pane.scrollTop).toBe(123)
  })

  it('keeps the same reply DOM node when streaming becomes persisted', () => {
    const parent = msg({ id: 'question', author: human('u1', 'Amo') })
    const stream = msg({ id: 'answer', author: machine(), parentId: parent.id, text: 'Checking', isStreaming: true })
    const props = { controls: { messages: [parent.message], currentUserId: 'u1' }, selected: null, active: null, map: false, jump: null, onSelect: vi.fn(), onOpenRef: vi.fn(), onReply: vi.fn(), onJump: vi.fn() }
    const { container, rerender } = render(<ShapeDiscussion {...props} threads={discussionThreads([parent, stream])} />)
    const node = container.querySelector('[data-mid="answer"]')
    expect(node?.closest('[data-depth]')).toHaveAttribute('data-depth', '1')
    const complete = msg({ id: 'answer', author: machine(), parentId: parent.id, text: 'The source answers this.', isStreaming: false })
    rerender(<ShapeDiscussion {...props} threads={discussionThreads([parent, complete])} />)
    expect(container.querySelector('[data-mid="answer"]')).toBe(node)
    expect(node).toHaveTextContent('The source answers this.')
  })
})


describe('searchable discussion map', () => {
  it('focuses a matched human thought with its ancestry and citations, and restores query, focus, zoom and pan after Threads', async () => {
    const article: MessageRef = { entity: 'reading_items', id: 'reading', label: 'An Alien Mind', quote: 'An exact repeated passage', quote_occurrence: 1, content_sha256: 'a'.repeat(64) }
    const study: MessageRef = { entity: 'reading_items', id: 'study', label: 'Timing study', quote: 'An external observation' }
    const parent = msg({ id: 'map-parent', author: human('u1', 'Amo'), text: 'My clinical experience', refs: [article] })
    const child = msg({ id: 'map-child', author: human('u2', 'Dan'), text: 'The delay matters here', parentId: parent.id, refs: [study] })
    const grandchild = msg({ id: 'map-grandchild', author: human('u1', 'Amo'), text: 'How could we test that?', parentId: child.id })
    const other = msg({ id: 'map-other', author: human('u1', 'Amo'), text: 'An unrelated thought' })
    const threads = discussionThreads([parent, child, grandchild, other])
    const jump = vi.fn(), openRef = vi.fn(), select = vi.fn()
    const props = { threads, controls: { messages: [], currentUserId: 'u1' }, selected: article, active: null, jump: null, onSelect: select, onOpenRef: openRef, onReply: vi.fn(), onJump: jump }
    const { container, rerender } = render(<ShapeDiscussion {...props} map />)
    const search = screen.getByRole('searchbox')
    fireEvent.change(search, { target: { value: 'Dan delay' } })
    expect(screen.getByRole('status')).toHaveTextContent('1 match')
    fireEvent.keyDown(search, { key: 'Enter' })
    expect(container.querySelector('[data-map-id="map-child"]')).toHaveAttribute('data-focused', 'true')
    expect(container.querySelector('[data-map-id="map-parent"]')).not.toBeNull()
    expect(container.querySelector('[data-map-id="source:study"]')).not.toBeNull()
    expect(container.querySelector('[data-map-id="source:reading"]')).not.toBeNull()
    expect(container.querySelector('[data-map-id="map-other"]')).toBeNull()
    expect(container.querySelector('[data-map-id="map-grandchild"]')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Open in thread ↗' }))
    expect(jump).toHaveBeenCalledWith(child.id)
    fireEvent.click(screen.getByRole('button', { name: /^Passage · Timing study An external observation$/ }))
    expect(openRef).toHaveBeenCalledWith(study, child.id)
    fireEvent.click(screen.getByRole('button', { name: /^Passage · An Alien Mind An exact repeated passage$/ }))
    expect(select).toHaveBeenCalledWith(threads[0])
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in map' }))
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)) })
    const pane = container.querySelector<HTMLElement>('.surf-map-scroll')!
    pane.scrollLeft = 225
    pane.scrollTop = 72
    fireEvent.scroll(pane)
    rerender(<ShapeDiscussion {...props} map={false} />)
    expect(screen.getByLabelText('Passage discussion threads')).toBeInTheDocument()
    rerender(<ShapeDiscussion {...props} map />)
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)) })
    expect(screen.getByRole('searchbox')).toHaveValue('Dan delay')
    expect(screen.getByRole('button', { name: 'Reset map zoom' })).toHaveTextContent('110%')
    expect(container.querySelector('[data-map-id="map-child"]')).toHaveAttribute('data-focused', 'true')
    expect(container.querySelector<HTMLElement>('.surf-map-scroll')!.scrollLeft).toBe(225)
    expect(container.querySelector<HTMLElement>('.surf-map-scroll')!.scrollTop).toBe(72)
    fireEvent.click(screen.getByRole('button', { name: 'Show whole map' }))
    expect(container.querySelectorAll('.surf-map-node--thought')).toHaveLength(4)
    fireEvent.click(screen.getByRole('button', { name: 'Hide 2 replies to Amo' }))
    expect(container.querySelector('[data-map-id="map-child"]')).toBeNull()
    expect(container.querySelector('[data-map-id="map-grandchild"]')).toBeNull()
    expect(container.querySelector('[data-map-id="map-other"]')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Show 2 replies to Amo' }))
    expect(container.querySelectorAll('.surf-map-node--thought')).toHaveLength(4)
  })

  it.each([0, 1])('centers a focused path when a token changes layout after %i scheduled frames', (framesBeforeToken) => {
    const frames = new Map<number, FrameRequestCallback>()
    let frameId = 0
    vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((callback) => {
      frames.set(++frameId, callback)
      return frameId
    })
    vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation((id) => { frames.delete(id) })
    const flushFrame = () => act(() => {
      const callbacks = [...frames.values()]
      frames.clear()
      callbacks.forEach((callback) => callback(performance.now()))
    })
    const root = msg({ id: 'focus-root', author: human('u1', 'Amo'), text: 'Root thought' })
    const child = msg({ id: 'focus-stream', author: machine(), text: 'An answer starts', parentId: root.id, isStreaming: true })
    const props = { controls: { messages: [], currentUserId: null }, selected: null, active: null, jump: null, onSelect: vi.fn(), onOpenRef: vi.fn(), onReply: vi.fn(), onJump: vi.fn() }
    const { container, rerender, unmount } = render(<ShapeDiscussion {...props} threads={discussionThreads([root, child])} map />)
    const pane = container.querySelector<HTMLElement>('.surf-map-scroll')!
    Object.defineProperties(pane, { clientWidth: { value: 300 }, clientHeight: { value: 300 } })
    flushFrame()
    pane.scrollLeft = 80
    pane.scrollTop = 10
    fireEvent.scroll(pane)
    fireEvent.click(screen.getByRole('button', { name: 'Focus path for Dialectic: An answer starts' }))
    for (let index = 0; index < framesBeforeToken; index += 1) flushFrame()
    const queuedFrames = [...frames.keys()]
    rerender(<ShapeDiscussion {...props} threads={discussionThreads([root, { ...child, text: 'An answer starts and continues' }])} map />)
    expect(queuedFrames.every((id) => !frames.has(id))).toBe(true)
    flushFrame()
    flushFrame()
    expect(pane.scrollLeft).toBe(240)
    expect(pane.scrollTop).toBe(36)
    expect(container.querySelector('[data-map-id="focus-stream"]')).toHaveAttribute('data-focused', 'true')
    expect(screen.getByRole('button', { name: 'Reset map zoom' })).toHaveTextContent('100%')
    unmount()
  })

  it('returns compact panel focus on Escape and sends search selection focus to the map without losing its query', async () => {
    const thought = msg({ id: 'compact-focus', author: human('u2', 'Dan'), text: 'A precise searchable thought' })
    const { container } = render(<ShapeDiscussion threads={discussionThreads([thought])} controls={{ messages: [], currentUserId: null }} selected={null} active={null} jump={null} map onSelect={vi.fn()} onOpenRef={vi.fn()} onReply={vi.fn()} onJump={vi.fn()} />)
    const flushFrame = () => act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)) })
    await flushFrame()
    const pane = container.querySelector<HTMLElement>('.surf-map-scroll')!
    pane.scrollLeft = 225
    pane.scrollTop = 72
    fireEvent.scroll(pane)
    const searchOpener = screen.getByRole('button', { name: 'Search map' })
    fireEvent.click(searchOpener)
    await flushFrame()
    const search = screen.getByRole('searchbox')
    expect(search).toHaveFocus()
    fireEvent.change(search, { target: { value: 'Dan precise' } })
    fireEvent.keyDown(search, { key: 'Escape' })
    expect(searchOpener).toHaveFocus()
    expect(searchOpener).toHaveAttribute('aria-expanded', 'false')
    expect(search).toHaveValue('Dan precise')
    expect([pane.scrollLeft, pane.scrollTop]).toEqual([225, 72])
    fireEvent.click(searchOpener)
    await flushFrame()
    fireEvent.keyDown(search, { key: 'Enter' })
    await flushFrame()
    expect(pane).toHaveFocus()
    expect(searchOpener).toHaveAttribute('aria-expanded', 'false')
    expect(search).toHaveValue('Dan precise')
    expect(container.querySelector('[data-map-id="compact-focus"]')).toHaveAttribute('data-focused', 'true')
    const contextOpener = screen.getByRole('button', { name: 'Show selected map context' })
    fireEvent.click(contextOpener)
    const contextText = screen.getByLabelText('Selected context text')
    act(() => contextText.focus())
    fireEvent.keyDown(contextText, { key: 'Escape' })
    expect(contextOpener).toHaveFocus()
    expect(contextOpener).toHaveAttribute('aria-expanded', 'false')
    const controlsOpener = screen.getByRole('button', { name: 'Map controls' })
    fireEvent.click(controlsOpener)
    const zoom = screen.getByRole('button', { name: 'Zoom in map' })
    act(() => zoom.focus())
    fireEvent.keyDown(zoom, { key: 'Escape' })
    expect(controlsOpener).toHaveFocus()
    expect(controlsOpener).toHaveAttribute('aria-expanded', 'false')
  })

  it('fits the visible graph and offers keyboard controls without hijacking search input', () => {
    const root = msg({ id: 'keyboard-root', author: human('u1', 'Amo'), text: 'Root thought' })
    const child = msg({ id: 'keyboard-child', author: human('u2', 'Dan'), text: 'Child thought', parentId: root.id })
    const { container } = render(<ShapeDiscussion threads={discussionThreads([root, child])} controls={{ messages: [], currentUserId: null }} selected={null} active={null} jump={null} map onSelect={vi.fn()} onOpenRef={vi.fn()} onReply={vi.fn()} onJump={vi.fn()} />)
    const pane = container.querySelector<HTMLElement>('.surf-map-scroll')!
    Object.defineProperties(pane, { clientWidth: { value: 300 }, clientHeight: { value: 300 } })
    fireEvent.click(screen.getByRole('button', { name: 'Fit view' }))
    expect(screen.getByRole('button', { name: 'Reset map zoom' })).toHaveTextContent('54%')
    fireEvent.click(screen.getByRole('button', { name: 'Reset map zoom' }))
    fireEvent.keyDown(screen.getByRole('searchbox'), { key: '-' })
    expect(screen.getByRole('button', { name: 'Reset map zoom' })).toHaveTextContent('100%')
    fireEvent.keyDown(pane, { key: '+' })
    expect(screen.getByRole('button', { name: 'Reset map zoom' })).toHaveTextContent('110%')
    fireEvent.keyDown(pane, { key: 'ArrowRight' })
    expect(pane.scrollLeft).toBe(120)
    fireEvent.keyDown(pane, { key: '0' })
    expect(screen.getByRole('button', { name: 'Reset map zoom' })).toHaveTextContent('54%')
  })
})
