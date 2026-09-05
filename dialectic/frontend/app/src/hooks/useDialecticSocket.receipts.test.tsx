import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDialecticSocket } from './useDialecticSocket'
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
    await act(async () => Socket.latest.receive('message_created', { client_request_id: sent.payload.client_request_id, thread_id: 'previous-branch' }))
    await expect(accepted).resolves.toBe(true)
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
