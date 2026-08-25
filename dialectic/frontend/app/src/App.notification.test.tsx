import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { api } from './lib/api.ts'
import { useAppStore } from './stores/appStore.ts'
import type { Message, Room, Thread, UserRoom } from './types/index.ts'
import type { RoomNavigation } from './hooks/useRoomNavigation.ts'
import { ChatLayout } from './App.tsx'

const socket = vi.hoisted(() => ({
  refreshMemories: vi.fn(),
  refreshPresence: vi.fn(),
  refreshReactions: vi.fn(),
  refreshAttachments: vi.fn(),
}))

vi.mock('./hooks/useDialecticSocket.ts', () => ({
  useDialecticSocket: () => ({
    isConnected: true,
    send: vi.fn(() => true),
    sendMessage: vi.fn(() => true),
    sendDeepDive: vi.fn(),
    sendTypingStart: vi.fn(),
    sendTypingStop: vi.fn(),
    sendTypingContent: vi.fn(),
    invokeProtocol: vi.fn(),
    advanceProtocol: vi.fn(),
    abortProtocol: vi.fn(),
    forkThread: vi.fn(),
    createCommitment: vi.fn(),
    recordConfidence: vi.fn(),
    resolveCommitment: vi.fn(),
    markMessageRead: vi.fn(() => true),
    editMessageContent: vi.fn(),
    deleteMessage: vi.fn(),
    toggleReaction: vi.fn(),
    ...socket,
  }),
}))
vi.mock('./hooks/useDocumentVisibility.ts', () => ({
  useDocumentVisibility: () => true,
}))
vi.mock('./hooks/useAwayAlerts.ts', () => ({ useAwayAlerts: vi.fn() }))
vi.mock('./hooks/usePushSubscription.ts', () => ({
  usePushSubscription: () => ({ state: 'unsupported', enable: vi.fn() }),
}))
vi.mock('./hooks/useWorkspaceObjects.ts', () => ({
  useWorkspaceObjects: () => ({ status: 'idle', objects: [], refresh: vi.fn() }),
}))
vi.mock('./hooks/useFieldMarks.ts', () => ({
  useFieldMarks: () => ({ status: 'idle' }),
}))
vi.mock('./hooks/useAtlas.ts', () => ({
  useAtlas: () => ({ status: 'idle' }),
}))
vi.mock('./components/layout/AppLayout', () => ({
  AppLayout: ({ main }: { main: ReactNode }) => main,
}))
vi.mock('./components/workspace/WorkspaceSceneFrame', () => ({
  WorkspaceSceneFrame: ({
    scene,
    content,
  }: {
    scene: string
    content: Record<string, ReactNode>
  }) => content[scene] ?? null,
}))
vi.mock('./components/chat/MessageList', () => ({
  MessageList: ({
    messages,
    jumpTarget,
  }: {
    messages: Message[]
    jumpTarget: { id: string; nonce: number } | null
  }) => (
    <div
      data-testid="message-list"
      data-message-ids={messages.map((message) => message.id).join(',')}
      data-jump-target={jumpTarget?.id ?? ''}
    />
  ),
}))
vi.mock('./components/analytics/BriefingPanel', () => ({ BriefingPanel: () => null }))
vi.mock('./components/stakes/CommitmentSurface', () => ({ CommitmentSurface: () => null }))
vi.mock('./components/layout/RoomHeader', () => ({ RoomHeader: () => null }))
vi.mock('./components/chat/ParticipantsBar', () => ({ ParticipantsBar: () => null }))
vi.mock('./components/chat/TypingIndicator', () => ({ TypingIndicator: () => null }))
vi.mock('./components/chat/MessageInput', () => ({ MessageInput: () => null }))

const room = {
  id: 'room-1',
  name: 'Iran/Hormuz Trading Room',
  token: 'room-token',
  is_home: false,
} as Room
const thread = {
  id: 'thread-1',
  room_id: room.id,
  parent_thread_id: null,
  title: 'Main',
  message_count: 1,
} as Thread
const roomDescriptor = {
  ...room,
  can_manage_home: false,
  unread_count: 0,
  last_message_at: null,
  last_message_preview: null,
  last_read_at: null,
  joined_at: null,
} as UserRoom

function message(id: string, threadId: string = thread.id): Message {
  return {
    id,
    thread_id: threadId,
    sequence: 1,
    created_at: '2026-08-17T01:00:00+00:00',
    speaker_type: 'human',
    user_id: 'user-1',
    message_type: 'text',
    content: id,
  } as Message
}

function navigation(messageId: string): RoomNavigation {
  return {
    rooms: [roomDescriptor],
    loading: false,
    ready: true,
    error: null,
    accessError: null,
    clearAccessError: vi.fn(),
    refreshRooms: vi.fn(async () => [roomDescriptor]),
    navigate: vi.fn(async () => true),
    enterGrantedRoom: vi.fn(async () => true),
    objectId: null,
    viewId: null,
    messageId,
  }
}

beforeEach(() => {
  useAppStore.setState(useAppStore.getInitialState(), true)
  useAppStore.setState({
    user: { id: 'user-1', display_name: 'Amo' },
    accessToken: 'jwt',
    isAuthenticated: true,
    currentRoom: room,
    roomToken: room.token,
    currentThread: thread,
    threads: [thread],
    workspaceScene: 'record',
  })
  vi.spyOn(api, 'setAccessToken').mockImplementation(() => undefined)
  vi.spyOn(api, 'setRoomToken').mockImplementation(() => undefined)
  vi.spyOn(api, 'getGenealogy').mockResolvedValue([])
  vi.spyOn(api, 'getRoomMembers').mockResolvedValue([])
  vi.spyOn(api, 'getTradingConfig').mockResolvedValue(null)
  socket.refreshMemories.mockReset()
  socket.refreshPresence.mockReset()
  socket.refreshReactions.mockReset()
  socket.refreshAttachments.mockReset()
})

describe('notification message hydration', () => {
  it('installs context before emitting the jump target', async () => {
    const context = [message('before'), message('target'), message('after')]
    const getContext = vi.spyOn(api, 'getMessageContext').mockResolvedValue(context)
    const getMessages = vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: [] })

    render(<ChatLayout nav={navigation('target')} />)

    await waitFor(() => expect(getContext).toHaveBeenCalledWith(thread.id, 'target'))
    expect(getMessages).not.toHaveBeenCalled()
    await waitFor(() => {
      expect(screen.getByTestId('message-list')).toHaveAttribute(
        'data-jump-target', 'target',
      )
    })
    expect(screen.getByTestId('message-list')).toHaveAttribute(
      'data-message-ids', 'before,target,after',
    )
    expect(socket.refreshAttachments).toHaveBeenCalled()
    expect(socket.refreshReactions).toHaveBeenCalled()
  })

  it('falls back to latest history when the message is gone', async () => {
    vi.spyOn(api, 'getMessageContext').mockRejectedValue(new Error('not found'))
    const latest = [message('latest')]
    const getMessages = vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: latest })

    render(<ChatLayout nav={navigation('deleted')} />)

    await waitFor(() => expect(getMessages).toHaveBeenCalledWith(thread.id, 200))
    await waitFor(() => expect(useAppStore.getState().messages).toEqual(latest))
    expect(screen.getByTestId('message-list')).toHaveAttribute(
      'data-jump-target', '',
    )
    expect(socket.refreshAttachments).toHaveBeenCalled()
    expect(socket.refreshReactions).toHaveBeenCalled()
  })

  it('falls back when a context response omits the deleted target', async () => {
    vi.spyOn(api, 'getMessageContext').mockResolvedValue([message('old-context')])
    const latest = [message('latest')]
    const getMessages = vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: latest })

    render(<ChatLayout nav={navigation('deleted')} />)

    await waitFor(() => expect(getMessages).toHaveBeenCalledWith(thread.id, 200))
    await waitFor(() => expect(useAppStore.getState().messages).toEqual(latest))
    expect(screen.getByTestId('message-list')).toHaveAttribute('data-jump-target', '')
  })

  it('does not let a slower prior destination overwrite the next one', async () => {
    const nextThread = {
      ...thread,
      id: 'thread-2',
      parent_thread_id: thread.id,
    }
    let resolveFirst: ((messages: Message[]) => void) | null = null
    const firstContext = new Promise<Message[]>((resolve) => {
      resolveFirst = resolve
    })
    vi.spyOn(api, 'getMessageContext').mockImplementation(async (threadId) => {
      if (threadId === thread.id) return firstContext
      return [message('target-2', nextThread.id)]
    })
    vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: [] })
    const { rerender } = render(<ChatLayout nav={navigation('target-1')} />)
    await waitFor(() => {
      expect(api.getMessageContext).toHaveBeenCalledWith(thread.id, 'target-1')
    })

    act(() => {
      useAppStore.setState({ currentThread: nextThread, threads: [thread, nextThread] })
    })
    rerender(<ChatLayout nav={navigation('target-2')} />)
    await waitFor(() => {
      expect(screen.getByTestId('message-list')).toHaveAttribute(
        'data-jump-target', 'target-2',
      )
    })

    await act(async () => {
      resolveFirst?.([message('target-1')])
      await firstContext
    })
    expect(screen.getByTestId('message-list')).toHaveAttribute(
      'data-message-ids', 'target-2',
    )
    expect(screen.getByTestId('message-list')).toHaveAttribute(
      'data-jump-target', 'target-2',
    )
    expect(socket.refreshReactions).toHaveBeenCalledWith(nextThread.id)
    expect(socket.refreshReactions).not.toHaveBeenCalledWith(thread.id)
    expect(socket.refreshAttachments).toHaveBeenCalledWith(nextThread.id)
    expect(socket.refreshAttachments).not.toHaveBeenCalledWith(thread.id)
  })
})
