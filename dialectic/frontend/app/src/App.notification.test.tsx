import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { api } from './lib/api.ts'
import { useAppStore } from './stores/appStore.ts'
import type { Message, Room, Thread, UserRoom } from './types/index.ts'
import type { RoomNavigation } from './hooks/useRoomNavigation.ts'
import type { AtlasProjection } from './types/atlas.ts'
import type { GeoScope, WorldSignal } from './types/geo.ts'
import { ChatLayout } from './App.tsx'

const socket = vi.hoisted(() => ({
  refreshMemories: vi.fn(),
  refreshPresence: vi.fn(),
  refreshReactions: vi.fn(),
  refreshAttachments: vi.fn(),
}))

const projections = vi.hoisted(() => ({
  refreshGeo: vi.fn(),
  refreshAtlas: vi.fn(),
}))
const atlasHook = vi.hoisted(() => vi.fn())
const geoHook = vi.hoisted(() => vi.fn())

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
vi.mock('./hooks/useGeoScopes.ts', () => ({
  useGeoScopes: geoHook,
}))
vi.mock('./hooks/useAtlas.ts', () => ({
  useAtlas: atlasHook,
}))
vi.mock('./components/workspace/focus/FocusSurface.tsx', () => ({
  FocusSurface: ({ onGeoChanged }: { onGeoChanged: () => void }) => (
    <button type="button" onClick={onGeoChanged}>Complete scope write</button>
  ),
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

function navigation(
  messageId: string, objectId: string | null = null,
  roomList: UserRoom[] = [roomDescriptor],
  viewId: string | null = null,
): RoomNavigation {
  return {
    rooms: roomList,
    loading: false,
    ready: true,
    error: null,
    accessError: null,
    clearAccessError: vi.fn(),
    refreshRooms: vi.fn(async () => roomList),
    navigate: vi.fn(async () => true),
    enterGrantedRoom: vi.fn(async () => true),
    objectId,
    viewId,
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
  projections.refreshGeo.mockReset()
  projections.refreshAtlas.mockReset()
  atlasHook.mockReset()
  atlasHook.mockReturnValue({ status: 'loading', retry: projections.refreshAtlas })
  geoHook.mockReset()
  geoHook.mockReturnValue({ status: 'loading', retry: projections.refreshGeo })
})

const placedScope: GeoScope = {
  id: 'geo_scope:scope-1',
  room_id: room.id,
  subject: { entity: 'rooms', id: room.id },
  kind: 'point',
  geometry: { type: 'Point', coordinates: [56.3, 26.5] },
  label: 'Hormuz placement',
  authority: 'human_confirmed',
  provenance: { provider: 'human', acquisition: 'human', credit: 'fixture' },
  source_state: 'ok',
  revision_action: 'place',
  review_state: 'accepted',
  freshness: {
    state: 'not_applicable', retrieved_at: '2026-08-25T18:00:00Z',
  },
  centroid: [56.3, 26.5],
  retrieved_at: '2026-08-25T18:00:00Z',
  created_at: '2026-08-25T18:00:00Z',
}

function atlasProjection(
  nodes: AtlasProjection['nodes'], scopes: GeoScope[] = [],
): AtlasProjection {
  return {
    generated_at: '2026-08-25T18:00:00Z',
    nodes,
    edges: [],
    scopes,
    signals: [],
    signal_sources: { status: 'not_configured', sources: [] },
  }
}

describe('World Synapse navigation', () => {
  it('enables Atlas in an ordinary room when Atlas is the active scene', () => {
    useAppStore.setState({ workspaceScene: 'atlas' })
    vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: [] })

    render(<ChatLayout nav={navigation('')} />)

    expect(atlasHook).toHaveBeenCalledWith(true)
  })

  it('opens Bench World inside the same room without dropping the selected object', () => {
    useAppStore.setState({ workspaceScene: 'bench' })
    geoHook.mockReturnValue({
      status: 'ready',
      projection: {
        generated_at: '2026-08-25T18:00:00Z', room_id: room.id,
        scopes: [placedScope],
      },
      retry: projections.refreshGeo,
    })
    vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: [] })
    const nav = navigation('', 'reading:r1')

    render(<ChatLayout nav={nav} />)
    fireEvent.click(screen.getByRole('button', { name: /World/ }))

    expect(nav.navigate).toHaveBeenCalledWith({
      roomId: room.id,
      threadId: null,
      scene: 'atlas',
      object: 'reading:r1',
      view: `world;room=${room.id}`,
    }, 'push')
  })

  it('opens World mode inside the same room with the same Focus object', () => {
    useAppStore.setState({ workspaceScene: 'atlas' })
    atlasHook.mockReturnValue({
      status: 'ready',
      projection: atlasProjection([{
        id: `room:${room.id}`, kind: 'room', room_id: room.id,
        branch_id: null, title: room.name ?? 'Room', summary: '', status: '',
        due: false, created_at: '2026-08-25T00:00:00Z',
        updated_at: '2026-08-25T00:00:00Z',
      }]),
      retry: projections.refreshAtlas,
    })
    vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: [] })
    const nav = navigation('', 'field_mark:causal')

    render(<ChatLayout nav={nav} />)
    fireEvent.click(screen.getByRole('button', { name: 'World' }))

    expect(nav.navigate).toHaveBeenCalledWith({
      roomId: room.id,
      threadId: null,
      scene: 'atlas',
      object: 'field_mark:causal',
      view: `world;room=${room.id}`,
    }, 'push')
  })

  it('keeps a selected scope in Atlas instead of falling back to Record', () => {
    useAppStore.setState({ workspaceScene: 'atlas' })
    atlasHook.mockReturnValue({
      status: 'ready',
      projection: atlasProjection([{
        id: `room:${room.id}`, kind: 'room', room_id: room.id,
        branch_id: null, title: room.name ?? 'Room', summary: '', status: '',
        due: false, created_at: '2026-08-25T00:00:00Z',
        updated_at: '2026-08-25T00:00:00Z',
      }], [placedScope]),
      retry: projections.refreshAtlas,
    })
    vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: [] })
    const nav = navigation('')

    render(<ChatLayout nav={nav} />)
    fireEvent.click(screen.getByRole('button', { name: /Hormuz placement/ }))

    expect(nav.navigate).toHaveBeenCalledWith({
      roomId: room.id,
      threadId: null,
      scene: 'atlas',
      object: placedScope.id,
      messageId: null,
      view: null,
    }, 'push')
  })

  it('changes rooms without carrying the prior object or World camera', () => {
    const otherRoomId = 'room-2'
    useAppStore.setState({ workspaceScene: 'atlas' })
    atlasHook.mockReturnValue({
      status: 'ready',
      projection: atlasProjection([{
        id: `room:${otherRoomId}`, kind: 'room', room_id: otherRoomId,
        branch_id: null, title: 'Other room', summary: '', status: '', due: false,
        created_at: '2026-08-25T00:00:00Z', updated_at: '2026-08-25T00:00:00Z',
      }]),
      retry: projections.refreshAtlas,
    })
    vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: [] })
    const nav = navigation(
      '', 'field_mark:old', [roomDescriptor],
      `world:26.5,56.3,450000,0,-45;room=${room.id}`,
    )

    render(<ChatLayout nav={nav} />)
    fireEvent.click(screen.getByText('Other room'))

    expect(nav.navigate).toHaveBeenCalledWith({
      roomId: otherRoomId,
      threadId: null,
      scene: 'atlas',
      object: null,
      messageId: null,
      view: `world;room=${otherRoomId}`,
    }, 'push')
  })
})

describe('world projection refresh', () => {
  it('refreshes geo and atlas when a write finishes while both projections are loading', () => {
    vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: [] })
    render(<ChatLayout nav={navigation('', 'reading:r1')} />)

    fireEvent.click(screen.getByRole('button', { name: 'Complete scope write' }))

    expect(projections.refreshGeo).toHaveBeenCalledOnce()
    expect(projections.refreshAtlas).toHaveBeenCalledOnce()
  })

  it('places an Atlas-visible signal whose saved room capability is beyond index 200', async () => {
    const home = {
      id: 'home-room', name: 'Home', token: 'home-token', is_home: true,
    } as Room
    const homeThread = { ...thread, id: 'home-thread', room_id: home.id }
    const homeDescriptor = {
      ...roomDescriptor, ...home, can_manage_home: true,
    } as UserRoom
    const signal: WorldSignal = {
      id: 'world_signal:ais:contact-1', provider: 'ais', source_id: 'contact-1',
      room_id: room.id, layer: 'vessels', kind: 'point',
      geometry: { type: 'Point', coordinates: [56.3, 26.5] },
      provenance: {
        provider: 'ais', acquisition: 'adapter:ais', source_id: 'contact-1',
        url: null, credit: 'AIS credit',
      },
      source_state: 'ok', freshness: 'current', coverage: 'receiver footprint',
      observed_at: '2026-08-25T17:58:00Z', retrieved_at: '2026-08-25T17:59:00Z',
      expires_at: '2026-08-25T18:10:00Z', label: 'Ordinary room vessel', details: {},
    }
    const readOnlySignal: WorldSignal = {
      ...signal,
      id: 'world_signal:ais:no-capability', source_id: 'no-capability',
      room_id: 'unavailable-room', label: 'Unavailable room vessel',
      provenance: { ...signal.provenance, source_id: 'no-capability' },
    }
    const projection: AtlasProjection = {
      generated_at: '2026-08-25T18:00:00Z',
      nodes: [{
        id: `room:${room.id}`, kind: 'room', room_id: room.id, branch_id: null,
        title: room.name ?? 'Room', summary: '', status: '', due: false,
        created_at: '2026-08-25T00:00:00Z', updated_at: '2026-08-25T00:00:00Z',
      }, {
        id: 'room:unavailable-room', kind: 'room', room_id: 'unavailable-room',
        branch_id: null, title: 'Unavailable room', summary: '', status: '', due: false,
        created_at: '2026-08-25T00:00:00Z', updated_at: '2026-08-25T00:00:00Z',
      }],
      edges: [], scopes: [], signals: [signal, readOnlySignal],
      signal_sources: {
        status: 'configured',
        sources: [{
          provider: 'ais', configured_room_ids: [room.id, 'unavailable-room'], source_state: 'ok',
          freshness: 'current', coverage: 'receiver footprint', observed_at: null,
          retrieved_at: '2026-08-25T17:59:00Z', expires_at: null, signal_count: 2,
        }],
      },
    }
    atlasHook.mockReturnValue({
      status: 'ready', projection, retry: projections.refreshAtlas,
    })
    useAppStore.setState({
      currentRoom: home, roomToken: home.token, currentThread: homeThread,
      threads: [homeThread], workspaceScene: 'atlas',
    })
    vi.spyOn(api, 'getMessages').mockResolvedValue({ messages: [] })
    const place = vi.spyOn(api, 'placeWorldSignal').mockResolvedValue({} as GeoScope)
    const fillerRooms = Array.from({ length: 200 }, (_, index): UserRoom => ({
      ...roomDescriptor,
      id: `filler-room-${index}`,
      token: `filler-token-${index}`,
    }))
    const savedRooms = [homeDescriptor, ...fillerRooms, roomDescriptor]
    expect(savedRooms.findIndex((savedRoom) => savedRoom.id === room.id)).toBeGreaterThan(200)

    render(<ChatLayout nav={navigation('', null, savedRooms)} />)
    expect(screen.getByText('Unavailable room vessel')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Place Unavailable room vessel' })).toBeNull()
    fireEvent.click(screen.getByText('Unavailable room vessel'))
    expect(place).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Place Ordinary room vessel' }))

    await waitFor(() => expect(place).toHaveBeenCalledWith(
      room.id, signal.id, room.token,
    ))
  })
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
