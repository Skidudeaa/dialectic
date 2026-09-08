import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDialecticSocket } from './useDialecticSocket'
import { api } from '../lib/api'
import { useAppStore } from '../stores/appStore'

class Socket {
  static OPEN = 1
  static latest: Socket
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  send = vi.fn()
  close = vi.fn()
  constructor() { Socket.latest = this }
  receive(type: string, payload: Record<string, unknown>) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ type, payload }) }))
  }
}

beforeEach(() => {
  vi.stubGlobal('WebSocket', Socket)
  vi.spyOn(api, 'getThreads').mockResolvedValue([])
  useAppStore.setState({ ...useAppStore.getInitialState(),
    currentRoom: { id: 'room', name: 'Room', token: 'token', is_home: false }, roomToken: 'token',
    user: { id: 'amo', display_name: 'Amo' },
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })

describe('confirmed source contributions', () => {
  it('waits for its own receipt, including after the reader changes branch', async () => {
    const { result } = renderHook(() => useDialecticSocket())
    Socket.latest.readyState = Socket.OPEN
    let settled = false
    const accepted = result.current.sendMessageWithReceipt('My thought').then((ok) => { settled = true; return ok })
    const sent = JSON.parse(Socket.latest.send.mock.calls.at(-1)![0])
    expect(sent.payload.client_request_id).toEqual(expect.any(String))
    await act(async () => Socket.latest.receive('message_created', { client_request_id: 'another-tab' }))
    expect(settled).toBe(false)
    await act(async () => Socket.latest.receive('message_created', { id: 'accepted-comment', client_request_id: sent.payload.client_request_id, thread_id: 'previous-branch' }))
    await expect(accepted).resolves.toEqual({ id: 'accepted-comment', thread_id: 'previous-branch' })
    expect(useAppStore.getState().messages).toEqual([])
  })

  it('returns a source rejection to the composer', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const { result } = renderHook(() => useDialecticSocket())
    Socket.latest.readyState = Socket.OPEN
    const accepted = result.current.sendMessageWithReceipt('Keep this draft')
    const assertion = expect(accepted).rejects.toThrow('The source changed')
    const sent = JSON.parse(Socket.latest.send.mock.calls.at(-1)![0])
    await act(async () => Socket.latest.receive('error', { client_request_id: sent.payload.client_request_id, error: 'The source changed' }))
    await assertion
  })

  it('does not report socket acceptance as stored when confirmation never arrives', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useDialecticSocket())
    Socket.latest.readyState = Socket.OPEN
    const accepted = result.current.sendMessageWithReceipt('Unconfirmed thought')
    const assertion = expect(accepted).rejects.toThrow('Send was not confirmed')
    await act(async () => vi.advanceTimersByTime(15000))
    await assertion
  })
})


describe('streamed reply identity', () => {
  it('keeps the triggering parent and source from the first token through completion', async () => {
    const thread = { id: 'thread', room_id: 'room', parent_thread_id: null, title: null, message_count: 0 }
    useAppStore.setState({ currentThread: thread })
    renderHook(() => useDialecticSocket())
    const refs = [{ entity: 'reading_items', id: 'source', label: 'Article', quote: 'The second passage', quote_occurrence: 1, content_sha256: 'hash' }]
    const identity = { message_id: 'answer', thread_id: thread.id, references_message_id: 'exact-question', metadata: { refs }, speaker_type: 'llm_primary' }
    await act(async () => Socket.latest.receive('llm_streaming', { ...identity, token: 'One ' }))
    const started = useAppStore.getState().streamingMessage
    expect(started).toMatchObject({ id: 'answer', references_message_id: 'exact-question', metadata: { refs } })
    await act(async () => Socket.latest.receive('llm_streaming', { ...identity, token: 'answer.' }))
    expect(useAppStore.getState().streamingContent).toBe('One answer.')
    expect(useAppStore.getState().streamingMessage?.created_at).toBe(started?.created_at)
    await act(async () => Socket.latest.receive('llm_streaming', { ...identity, thread_id: 'elsewhere', token: 'Wrong thread' }))
    expect(useAppStore.getState().streamingContent).toBe('One answer.')
    await act(async () => Socket.latest.receive('llm_done', { ...identity, content: 'One answer.', sequence: 9 }))
    expect(useAppStore.getState().messages).toEqual([expect.objectContaining({ id: 'answer', references_message_id: 'exact-question', content: 'One answer.', metadata: { refs } })])
    expect(useAppStore.getState().streamingMessage).toBeNull()
    expect(useAppStore.getState().streamingContent).toBe('')
  })

  it('does not mix tokens across message identities and clears ancestry when changing rooms', async () => {
    useAppStore.setState({ currentThread: { id: 'thread', room_id: 'room', parent_thread_id: null, title: null, message_count: 0 } })
    renderHook(() => useDialecticSocket())
    await act(async () => Socket.latest.receive('llm_streaming', { thread_id: 'thread', message_id: 'first', token: 'First text', references_message_id: 'parent' }))
    await act(async () => Socket.latest.receive('llm_streaming', { thread_id: 'thread', message_id: 'second', token: 'Second text' }))
    expect(useAppStore.getState().streamingContent).toBe('Second text')
    expect(useAppStore.getState().streamingMessage?.references_message_id).toBeNull()
    await act(async () => useAppStore.getState().setRoom({ id: 'next-room', name: 'Next', token: 'next', is_home: false }, 'next'))
    expect(useAppStore.getState().streamingMessage).toBeNull()
    expect(useAppStore.getState().streamingContent).toBe('')
  })
})


it('preserves the active branch response when unrelated work finishes or stays silent', async () => {
  useAppStore.setState({ currentThread: { id: 'thread', room_id: 'room', parent_thread_id: null, title: null, message_count: 0 } })
  renderHook(() => useDialecticSocket())
  const identity = { thread_id: 'thread', message_id: 'branch-response', references_message_id: 'question', token: 'Still answering' }
  await act(async () => Socket.latest.receive('llm_streaming', identity))
  await act(async () => Socket.latest.receive('message_created', { id: 'annotation', thread_id: 'thread', speaker_type: 'llm_annotator', content: 'Background note' }))
  await act(async () => Socket.latest.receive('llm_done', { message_id: 'research-row', stream_message_id: 'research-stream', thread_id: 'thread', content: 'A separate brief' }))
  await act(async () => Socket.latest.receive('llm_cancelled', { thread_id: 'thread', reason: 'no_interjection' }))
  await act(async () => Socket.latest.receive('llm_error', { thread_id: 'thread', message_id: 'other-error', error: 'Another task failed' }))
  await act(async () => Socket.latest.receive('llm_error', { thread_id: 'thread', error: 'A different request was deleted before it started' }))
  expect(useAppStore.getState().streamingContent).toBe('Still answering')
  expect(useAppStore.getState().streamingMessage?.id).toBe('branch-response')
  expect(useAppStore.getState().messages.map((message) => message.id)).toEqual(['annotation', 'research-row'])
  await act(async () => Socket.latest.receive('llm_done', { thread_id: 'thread', message_id: 'persisted-research', stream_message_id: 'branch-response', content: 'Finished' }))
  expect(useAppStore.getState().streamingMessage).toBeNull()
})
