import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useEffect, type ReactNode } from 'react'
import { ChatLayout } from './App.tsx'
import { useRoomNavigation, type RoomNavigation } from './hooks/useRoomNavigation.ts'
import { api } from './lib/api.ts'
import { useAppStore } from './stores/appStore.ts'
import type { Message, RoomDestination, Thread, UserRoom } from './types/index.ts'

const socket = vi.hoisted(() => ({ sendMessageWithReceipt: vi.fn(async () => ({ id: 'accepted-comment', thread_id: 'thread-1' })) }))

vi.mock('./hooks/useDialecticSocket.ts', () => {
  const actions = {
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
    refreshMemories: vi.fn(),
    refreshPresence: vi.fn(),
    refreshReactions: vi.fn(),
    refreshAttachments: vi.fn(),
    ...socket,
  }
  return { useDialecticSocket: () => actions }
})
vi.mock('./hooks/useDocumentVisibility.ts', () => ({ useDocumentVisibility: () => true }))
vi.mock('./hooks/useAwayAlerts.ts', () => ({ useAwayAlerts: vi.fn() }))
vi.mock('./hooks/usePushSubscription.ts', () => ({
  usePushSubscription: () => ({ state: 'unsupported', enable: vi.fn() }),
}))
vi.mock('./hooks/useWorkspaceObjects.ts', () => ({
  useWorkspaceObjects: () => ({ status: 'idle', objects: [], refresh: vi.fn() }),
}))
vi.mock('./hooks/useFieldMarks.ts', () => ({ useFieldMarks: () => ({ status: 'idle' }) }))
vi.mock('./hooks/useGeoScopes.ts', () => ({
  useGeoScopes: () => ({ status: 'loading', retry: vi.fn() }),
}))
vi.mock('./hooks/useAtlas.ts', () => ({
  useAtlas: () => ({ status: 'loading', retry: vi.fn() }),
}))
vi.mock('./hooks/useWorldObservations.ts', () => ({
  useWorldObservations: () => ({ status: 'loading', retry: vi.fn() }),
}))
vi.mock('./hooks/useTradingDesk.ts', () => ({
  useTradingDesk: () => ({
    bound: false,
    refresh: vi.fn(),
    ...Object.fromEntries(
      ['structure', 'quotes', 'polymarket', 'diff', 'trades', 'brief', 'news', 'portfolio']
        .map((key) => [key, { status: 'empty' }]),
    ),
  }),
}))
// The navigation hook, scene frame, Surface conversation and both composers
// stay real: their ownership and remount boundaries caused these regressions.
vi.mock('./components/layout/AppLayout', () => ({
  AppLayout: ({ main }: { main: ReactNode }) => main,
}))
vi.mock('./components/chat/MessageList', () => ({ MessageList: () => null }))
vi.mock('./components/analytics/BriefingPanel', () => ({ BriefingPanel: () => null }))
vi.mock('./components/stakes/CommitmentSurface', () => ({ CommitmentSurface: () => null }))
vi.mock('./components/layout/RoomHeader', () => ({ RoomHeader: () => null }))
vi.mock('./components/chat/ParticipantsBar', () => ({ ParticipantsBar: () => null }))
vi.mock('./components/chat/TypingIndicator', () => ({ TypingIndicator: () => null }))

const room: UserRoom = {
  id: 'room-1', name: 'First room', token: 'room-token', is_home: false,
  can_manage_home: false, unread_count: 0, last_message_at: null, last_message_preview: null,
}
const otherRoom: UserRoom = { ...room, id: 'room-2', name: 'Other room', token: 'other-token' }
const thread: Thread = {
  id: 'thread-1', room_id: room.id, parent_thread_id: null, title: 'Main', message_count: 0,
}
const branch: Thread = { ...thread, id: 'branch-1', parent_thread_id: thread.id, title: 'Branch' }
const otherThread: Thread = { ...thread, id: 'thread-2', room_id: otherRoom.id }

beforeEach(() => {
  window.sessionStorage.clear()
  window.localStorage.clear()
  window.history.replaceState(null, '', '/?room=room-1')
  useAppStore.setState(useAppStore.getInitialState(), true)
  useAppStore.setState({
    user: { id: 'user-1', display_name: 'Amo' },
    accessToken: 'jwt', isAuthenticated: true,
    currentRoom: room, roomToken: room.token,
    currentThread: thread, threads: [thread, branch], workspaceScene: 'surface',
  })
  vi.spyOn(api, 'setAccessToken').mockImplementation(() => undefined)
  vi.spyOn(api, 'setRoomToken').mockImplementation(() => undefined)
  vi.spyOn(api, 'getRooms').mockResolvedValue([room, otherRoom])
  vi.spyOn(api, 'getThreads').mockImplementation(async (roomId) => (
    roomId === room.id ? [thread, branch] : [otherThread]
  ))
  vi.spyOn(api, 'getGenealogy').mockResolvedValue([])
  vi.spyOn(api, 'getRoomMembers').mockResolvedValue([])
  vi.spyOn(api, 'getTradingConfig').mockResolvedValue(null)
  vi.spyOn(api, 'getMessages').mockResolvedValue([])
  vi.spyOn(api, 'getRoomCapabilities').mockResolvedValue({
    thesis_bound: false, auto_interjection: false, interjection_turn_threshold: 3,
    scheduler_running: false, jobs: [],
  })
  vi.spyOn(api, 'getReadingLibrary').mockResolvedValue({ items: [], next_before: null })
  socket.sendMessageWithReceipt.mockReset().mockResolvedValue({ id: 'accepted-comment', thread_id: thread.id })
})

function composer(): HTMLTextAreaElement {
  return screen.getByPlaceholderText(/think out loud/i)
}

function typeDraft(content: string): void {
  fireEvent.change(composer(), { target: { value: content } })
}

async function renderApp(): Promise<(destination: RoomDestination) => Promise<void>> {
  let currentNav: RoomNavigation
  function Harness() {
    const nav = useRoomNavigation()
    useEffect(() => { currentNav = nav }, [nav])
    return nav.ready ? <ChatLayout nav={nav} /> : null
  }
  render(<Harness />)
  await waitFor(() => expect(composer()).toBeEnabled())
  return async (destination) => {
    await act(async () => {
      expect(await currentNav.navigate(destination, 'push')).toBe(true)
    })
  }
}

async function selectScene(scene: 'Surface' | 'Record' | 'Library'): Promise<void> {
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Room views' }))
    .getByRole('button', { name: scene }))
  await waitFor(() => expect(useAppStore.getState().workspaceScene).toBe(scene.toLowerCase()))
  expect(document.querySelector(`[data-workspace-scene="${scene.toLowerCase()}"]`)).not.toBeNull()
}

async function submitPending(content: string): Promise<() => Promise<void>> {
  let accept: (sent: { id: string; thread_id: string }) => void
  socket.sendMessageWithReceipt.mockImplementationOnce(() => new Promise<{ id: string; thread_id: string }>((resolve) => {
    accept = resolve
  }))
  typeDraft(content)
  fireEvent.keyDown(composer(), { key: 'Enter' })
  expect(socket.sendMessageWithReceipt).toHaveBeenCalledWith(
    content, 'text', null, [], [], { anchor: null, refs: [] },
  )
  expect(composer()).toHaveValue(content)
  return async () => {
    await act(async () => { accept({ id: 'accepted-comment', thread_id: thread.id }) })
  }
}

describe('conversation drafts across scenes and destinations', () => {
  it.each([
    { label: 'a newer draft', edit: 'New unsent Record thought' },
    { label: 'the same text retyped after an edit', edit: 'First submitted Surface thought' },
  ])('keeps $label after an old Surface receipt and Record remount', async ({ edit }) => {
    await renderApp()
    const accept = await submitPending('First submitted Surface thought')
    await selectScene('Record')
    typeDraft('A distinct edit before the final draft')
    typeDraft(edit)

    await accept()
    expect(composer()).toHaveValue(edit)
    await selectScene('Library')
    await selectScene('Record')
    expect(composer()).toHaveValue(edit)
  })

  it('clears an accepted Surface draft without a newer edit, including after remount', async () => {
    await renderApp()
    const accept = await submitPending('This thought was accepted')
    await accept()
    expect(composer()).toHaveValue('')

    await selectScene('Library')
    await selectScene('Surface')
    expect(composer()).toHaveValue('')
  })

  it('retains unsent text through scene changes in the same room and thread', async () => {
    await renderApp()
    typeDraft('One destination, one unfinished thought')
    await selectScene('Record')
    expect(composer()).toHaveValue('One destination, one unfinished thought')
    await selectScene('Library')
    await selectScene('Surface')
    expect(composer()).toHaveValue('One destination, one unfinished thought')
    expect(useAppStore.getState().currentRoom?.id).toBe(room.id)
    expect(useAppStore.getState().currentThread?.id).toBe(thread.id)
  })

  it('starts with an empty Surface draft after real room navigation', async () => {
    const navigate = await renderApp()
    typeDraft('Room one private unfinished thought')
    await navigate({ roomId: otherRoom.id })

    expect(window.location.search).toBe('?room=room-2')
    expect(useAppStore.getState().currentRoom?.id).toBe(otherRoom.id)
    expect(useAppStore.getState().currentThread?.id).toBe(otherThread.id)
    expect(document.querySelector('[data-workspace-scene="surface"]')).not.toBeNull()
    expect(composer()).toHaveValue('')
    await selectScene('Record')
    expect(composer()).toHaveValue('')
  })

  it('clears drafts on thread changes while keeping the room destination', async () => {
    const navigate = await renderApp()
    await selectScene('Record')
    typeDraft('Root thread unfinished thought')
    await navigate({ roomId: room.id, threadId: branch.id })

    expect(window.location.search).toBe('?room=room-1&thread=branch-1')
    expect(useAppStore.getState().currentRoom?.id).toBe(room.id)
    expect(useAppStore.getState().currentThread?.id).toBe(branch.id)
    expect(document.querySelector('[data-workspace-scene="record"]')).not.toBeNull()
    expect(composer()).toHaveValue('')

    typeDraft('Branch-only unfinished thought')
    await navigate({ roomId: room.id })
    expect(window.location.search).toBe('?room=room-1')
    expect(useAppStore.getState().currentThread?.id).toBe(thread.id)
    expect(composer()).toHaveValue('')
  })

  it('keeps the new room draft when the old room Surface receipt arrives', async () => {
    const navigate = await renderApp()
    const accept = await submitPending('Sent from the first room')
    await navigate({ roomId: otherRoom.id })
    typeDraft('Unsent in the second room')
    await accept()
    await selectScene('Library')
    await selectScene('Record')

    expect(useAppStore.getState().currentRoom?.id).toBe(otherRoom.id)
    expect(useAppStore.getState().currentThread?.id).toBe(otherThread.id)
    expect(composer()).toHaveValue('Unsent in the second room')
  })
})


describe('simultaneous answers on the conversation surface', () => {
  it.each([['answer-A', 'answer-B'], ['answer-B', 'answer-A']])('keeps both branches mounted when %s finishes before %s', async (first, second) => {
    const refs = [{ entity: 'reading_items', id: 'article', label: 'Article', quote: 'Passage under discussion', content_sha256: 'revision', quote_occurrence: 1 }]
    const human = (id: string): Message => ({
      id, thread_id: thread.id, sequence: id === 'question-A' ? 1 : 2,
      created_at: new Date().toISOString(), speaker_type: 'human', user_id: 'user-1',
      message_type: 'text', content: `Discuss ${id}`, metadata: { refs },
    })
    vi.mocked(api.getMessages).mockResolvedValue([human('question-A'), human('question-B')])
    await renderApp()
    typeDraft('Keep my unfinished thought')
    await act(async () => {
      for (const [id, content] of [['answer-A', 'A1 '], ['answer-B', 'B1 '], ['answer-A', 'A2'], ['answer-B', 'B2']]) {
        useAppStore.getState().receiveStream({ id, thread_id: thread.id, references_message_id: id.replace('answer', 'question'), metadata: { refs } }, content)
      }
    })
    const row = (id: string) => document.querySelector(`[data-message-id="${id}"]`)!
    const firstNode = row(first)
    const secondNode = row(second)
    expect(firstNode).not.toBeNull()
    expect(secondNode).not.toBeNull()
    for (const id of ['answer-A', 'answer-B']) {
      expect(row(id)).toHaveTextContent(id === 'answer-A' ? 'A1 A2' : 'B1 B2')
      const parent = row(id)?.closest('.surf-branch')?.parentElement
      expect(parent?.querySelector(`[data-message-id="${id.replace('answer', 'question')}"]`)).not.toBeNull()
      expect(row(id).closest('.surf-passage-thread')).toHaveTextContent('Passage under discussion')
      expect(within(row(id) as HTMLElement).queryByRole('button', { name: 'Reply' })).toBeNull()
    }
    await act(async () => {
      const pending = useAppStore.getState().streamingMessages[first]
      useAppStore.getState().finishStream(first, { ...pending, sequence: 3, content: 'First final answer' })
    })
    expect(row(first)).toBe(firstNode)
    expect(row(second)).toBe(secondNode)
    expect(row(first)).toHaveTextContent('First final answer')
    expect(within(row(first) as HTMLElement).getByRole('button', { name: 'Reply' })).toBeEnabled()
    expect(within(row(second) as HTMLElement).queryByRole('button', { name: 'Reply' })).toBeNull()
    await act(async () => {
      const pending = useAppStore.getState().streamingMessages[second]
      useAppStore.getState().finishStream(second, { ...pending, sequence: 4, content: 'Second final answer' })
    })
    expect(row(first)).toBe(firstNode)
    expect(row(second)).toBe(secondNode)
    expect(row(second)).toHaveTextContent('Second final answer')
    expect(composer()).toHaveValue('Keep my unfinished thought')
  })

  it('retains a research row while another response streams and research completes', async () => {
    await renderApp()
    await act(async () => {
      useAppStore.getState().receiveStream({ id: 'research', thread_id: thread.id }, 'Research findings')
      useAppStore.getState().receiveStream({ id: 'summon', thread_id: thread.id }, 'An overlapping answer')
    })
    const researchRow = document.querySelector('[data-message-id="research"]')
    expect(researchRow).not.toBeNull()
    await act(async () => useAppStore.getState().finishStream('research', {
      ...useAppStore.getState().streamingMessages.research, sequence: 1, metadata: { source: 'deep_dive' },
    }))
    expect(document.querySelector('[data-message-id="research"]')).toBe(researchRow)
    expect(document.querySelector('[data-message-id="summon"]')).toHaveTextContent('An overlapping answer')
  })
})
