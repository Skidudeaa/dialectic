import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('workbox-core', () => ({ clientsClaim: vi.fn() }))
vi.mock('workbox-precaching', () => ({
  cleanupOutdatedCaches: vi.fn(),
  createHandlerBoundToURL: vi.fn(() => vi.fn()),
  precacheAndRoute: vi.fn(),
}))
vi.mock('workbox-routing', () => ({
  NavigationRoute: vi.fn(),
  registerRoute: vi.fn(),
}))
vi.mock('workbox-strategies', () => ({
  CacheFirst: vi.fn(),
  StaleWhileRevalidate: vi.fn(),
}))
vi.mock('workbox-expiration', () => ({ ExpirationPlugin: vi.fn() }))
vi.mock('workbox-cacheable-response', () => ({ CacheableResponsePlugin: vi.fn() }))

type WorkerListener = (event: unknown) => void

const listeners = new Map<string, WorkerListener>()
const matchAll = vi.fn()
const openWindow = vi.fn()
const workerSelf = {
  __WB_MANIFEST: [],
  skipWaiting: vi.fn(),
  addEventListener: vi.fn((type: string, listener: WorkerListener) => {
    listeners.set(type, listener)
  }),
  registration: { showNotification: vi.fn() },
  clients: { matchAll, openWindow },
}

interface ClickData {
  room_id?: string
  thread_id?: string
  message_id?: string
}

async function click(data: ClickData): Promise<void> {
  let pending: Promise<unknown> | undefined
  const close = vi.fn()
  listeners.get('notificationclick')?.({
    notification: { data, close },
    waitUntil(value: Promise<unknown>) {
      pending = value
    },
  })
  expect(close).toHaveBeenCalledOnce()
  await pending
}

beforeAll(async () => {
  vi.stubGlobal('self', workerSelf)
  await import('./sw')
})

beforeEach(() => {
  matchAll.mockReset()
  openWindow.mockReset()
})

describe('notification message destinations', () => {
  it('focuses the visible client and posts the complete warm destination', async () => {
    const hidden = {
      visibilityState: 'hidden',
      focus: vi.fn(),
      postMessage: vi.fn(),
    }
    const visible = {
      visibilityState: 'visible',
      focus: vi.fn().mockResolvedValue(undefined),
      postMessage: vi.fn((_data, ports: MessagePort[]) => {
        ports[0]?.postMessage({ type: 'navigation-received' })
      }),
      navigate: vi.fn(),
    }
    matchAll.mockResolvedValue([hidden, visible])

    await click({ room_id: 'r', thread_id: 't', message_id: 'm' })

    expect(hidden.focus).not.toHaveBeenCalled()
    expect(visible.focus).toHaveBeenCalledOnce()
    expect(visible.postMessage).toHaveBeenCalledWith(
      {
        type: 'open-message',
        roomId: 'r',
        threadId: 't',
        messageId: 'm',
      },
      [expect.any(MessagePort)],
    )
    expect(visible.navigate).not.toHaveBeenCalled()
    expect(openWindow).not.toHaveBeenCalled()
  })

  it('opens an encoded exact-message URL from a cold tap', async () => {
    matchAll.mockResolvedValue([])

    await click({
      room_id: 'room & one',
      thread_id: 'thread=two',
      message_id: 'message#three',
    })

    expect(openWindow).toHaveBeenCalledWith(
      '/?room=room+%26+one&thread=thread%3Dtwo&message=message%23three',
    )
  })

  it('navigates a warm client when no mounted listener acknowledges the tap', async () => {
    vi.useFakeTimers()
    const visible = {
      visibilityState: 'visible',
      focus: vi.fn().mockResolvedValue(undefined),
      postMessage: vi.fn(),
      navigate: vi.fn().mockResolvedValue(undefined),
    }
    matchAll.mockResolvedValue([visible])

    const pending = click({ room_id: 'r', thread_id: 't', message_id: 'm' })
    await vi.runAllTimersAsync()
    await pending

    expect(visible.navigate).toHaveBeenCalledWith('/?room=r&thread=t&message=m')
    vi.useRealTimers()
  })

  it('keeps legacy room-only warm and cold taps working', async () => {
    const visible = {
      visibilityState: 'visible',
      focus: vi.fn().mockResolvedValue(undefined),
      postMessage: vi.fn((_data, ports: MessagePort[]) => {
        ports[0]?.postMessage({ type: 'navigation-received' })
      }),
      navigate: vi.fn(),
    }
    matchAll.mockResolvedValueOnce([visible]).mockResolvedValueOnce([])

    await click({ room_id: 'legacy room' })
    expect(visible.postMessage).toHaveBeenCalledWith(
      { type: 'open-room', roomId: 'legacy room' },
      [expect.any(MessagePort)],
    )

    await click({ room_id: 'legacy room' })
    expect(openWindow).toHaveBeenCalledWith('/?room=legacy+room')
  })
})
