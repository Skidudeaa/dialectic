import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './styles/global.css'
import { useAppStore } from './stores/appStore.ts'
import { api } from './lib/api.ts'
import { AuthScreen } from './components/auth/AuthScreen.tsx'
import { RoomSelector } from './components/auth/RoomSelector.tsx'
import { useDialecticSocket } from './hooks/useDialecticSocket.ts'
import type { Message, Thread, TradingSnapshot, UserRoom } from './types/index.ts'
import { AppLayout } from './components/layout/AppLayout'
import { RoomHeader } from './components/layout/RoomHeader'
import { RoomSettingsDialog } from './components/layout/RoomSettingsDialog'
import { RoomList } from './components/sidebar/RoomList'
import { RightPanel } from './components/sidebar/RightPanel'
import { MessageList } from './components/chat/MessageList'
import { MessageInput } from './components/chat/MessageInput'
import { ParticipantsBar } from './components/chat/ParticipantsBar'
import { TypingIndicator } from './components/chat/TypingIndicator'
import { ProtocolPicker } from './components/protocols/ProtocolPicker'
import { ProtocolBanner } from './components/protocols/ProtocolBanner'
import { BriefingPanel } from './components/analytics/BriefingPanel'
import { CommitmentSurface } from './components/stakes/CommitmentSurface'

function RoomBriefing({ roomId }: { roomId: string }) {
  const [dismissed, setDismissed] = useState(false)
  if (dismissed) return null
  return <BriefingPanel roomId={roomId} onDismiss={() => setDismissed(true)} />
}

function accessTokenExpiry(token: string | null): number {
  if (!token) return 0
  try {
    const encoded = token.split('.')[1]
    if (!encoded) return 0
    const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    const payload = JSON.parse(window.atob(padded)) as { exp?: number }
    return typeof payload.exp === 'number' ? payload.exp * 1000 : 0
  } catch {
    return 0
  }
}

function ChatLayout() {
  const user = useAppStore((s) => s.user)
  const accessToken = useAppStore((s) => s.accessToken)
  const refreshToken = useAppStore((s) => s.refreshToken)
  const currentRoom = useAppStore((s) => s.currentRoom)
  const currentThread = useAppStore((s) => s.currentThread)
  const threads = useAppStore((s) => s.threads)
  const messages = useAppStore((s) => s.messages)
  const memories = useAppStore((s) => s.memories)
  const typingUsers = useAppStore((s) => s.typingUsers)
  const onlineUsers = useAppStore((s) => s.onlineUsers)
  const isLLMThinking = useAppStore((s) => s.isLLMThinking)
  const isLLMStreaming = useAppStore((s) => s.isLLMStreaming)
  const streamingContent = useAppStore((s) => s.streamingContent)
  const activeProtocol = useAppStore((s) => s.activeProtocol)
  const roomToken = useAppStore((s) => s.roomToken)
  const setRoom = useAppStore((s) => s.setRoom)
  const setThread = useAppStore((s) => s.setThread)
  const setThreads = useAppStore((s) => s.setThreads)
  const setMessages = useAppStore((s) => s.setMessages)
  const leaveRoom = useAppStore((s) => s.leaveRoom)
  const logout = useAppStore((s) => s.logout)
  const setTradingConfig = useAppStore((s) => s.setTradingConfig)

  const [rooms, setRooms] = useState<UserRoom[]>([])
  const [showProtocolPicker, setShowProtocolPicker] = useState(false)
  const [showSettings, setShowSettings] = useState(false)

  const handleLogout = useCallback(() => {
    if (refreshToken) void api.logoutSession(refreshToken).catch(() => undefined)
    logout()
  }, [refreshToken, logout])

  // Restore the persisted JWT into the API singleton after a page reload.
  api.setAccessToken(accessToken ?? '')
  if (roomToken) api.setRoomToken(roomToken)

  const {
    isConnected,
    send,
    sendMessage,
    sendTypingStart,
    sendTypingStop,
    sendTypingContent,
    invokeProtocol,
    advanceProtocol,
    abortProtocol,
    forkThread,
    createCommitment,
    recordConfidence,
    resolveCommitment,
    refreshThreads,
    refreshMemories,
    refreshPresence,
  } = useDialecticSocket()

  // Hydrate collaboration state that is not delivered by the socket handshake.
  useEffect(() => {
    if (!currentRoom || !roomToken) return
    api.setRoomToken(roomToken)
    void refreshThreads()
    void refreshMemories()
    void refreshPresence()

    if (accessToken) {
      api.getRooms()
        .then((data) => setRooms(data as UserRoom[]))
        .catch((error) => console.error('Failed to load rooms:', error))
    }
  }, [currentRoom, roomToken, accessToken, refreshThreads, refreshMemories, refreshPresence])

  // Load the selected branch's persisted history. Socket events then append live
  // messages, while the store deduplicates by message ID.
  useEffect(() => {
    if (!currentThread || !roomToken) return
    api.setRoomToken(roomToken)
    api.getMessages(currentThread.id, 200)
      .then((res) => {
        const data = res as { messages?: Message[] } | Message[]
        const history = Array.isArray(data) ? data : data.messages
        if (Array.isArray(history)) setMessages(history)
      })
      .catch((error) => console.error('Failed to load message history:', error))
  }, [currentThread, roomToken, setMessages])

  // Trading is an optional room extension.
  useEffect(() => {
    if (!currentRoom || !roomToken) return
    api.setRoomToken(roomToken)
    api.getTradingConfig(currentRoom.id).then((config) => {
      if (config && typeof config === 'object' && 'v' in config) {
        setTradingConfig(config as unknown as TradingSnapshot)
      } else {
        setTradingConfig(null)
      }
    }).catch(() => setTradingConfig(null))
  }, [currentRoom, roomToken, setTradingConfig])

  const switchRoom = useCallback(async (roomId: string) => {
    const nextRoom = rooms.find((room) => room.id === roomId)
    if (!nextRoom?.token || nextRoom.id === currentRoom?.id) return
    try {
      api.setRoomToken(nextRoom.token)
      const nextThreads = await api.getThreads(nextRoom.id) as Thread[]
      setRoom({ id: nextRoom.id, name: nextRoom.name, token: nextRoom.token }, nextRoom.token)
      setThreads(nextThreads)
      if (nextThreads.length > 0) setThread(nextThreads[0])
    } catch (error) {
      console.error('Failed to switch rooms:', error)
      window.alert(error instanceof Error ? error.message : 'Could not open that room')
    }
  }, [rooms, currentRoom?.id, setRoom, setThreads, setThread])

  const forkFromMessage = useCallback((messageId: string) => {
    if (!currentThread) return
    const title = window.prompt('Name this branch (optional)', '')
    if (title === null) return
    if (!forkThread(currentThread.id, messageId, title.trim() || undefined)) {
      window.alert('Reconnect before creating a branch.')
    }
  }, [currentThread, forkThread])

  const forkLatest = useCallback(() => {
    const lastMessage = [...messages].reverse().find((message) => message.id !== '__streaming__')
    if (!lastMessage) {
      window.alert('Add a message before creating a branch.')
      return
    }
    forkFromMessage(lastMessage.id)
  }, [messages, forkFromMessage])

  const handleResolveCommitment = useCallback((commitmentId: string) => {
    const resolution = window.prompt('Resolution: correct, incorrect, partial, or voided', 'correct')
    if (resolution === null) return
    const normalized = resolution.trim().toLowerCase()
    if (!['correct', 'incorrect', 'partial', 'voided'].includes(normalized)) {
      window.alert('Use correct, incorrect, partial, or voided.')
      return
    }
    resolveCommitment(commitmentId, normalized)
  }, [resolveCommitment])

  // In-flight LLM stream rendered as a synthetic message; llm_done replaces it
  // with the authoritative persisted message.
  const STREAMING_ID = '__streaming__'
  const displayMessages: Message[] = isLLMStreaming && streamingContent
    ? [...messages, {
        id: STREAMING_ID,
        thread_id: currentThread?.id ?? '',
        sequence: Number.MAX_SAFE_INTEGER,
        created_at: new Date().toISOString(),
        speaker_type: 'llm_primary',
        user_id: null,
        message_type: 'text',
        content: streamingContent,
      } as Message]
    : messages

  const userNames = useMemo(() => {
    const names: Record<string, string> = {}
    for (const participant of onlineUsers) names[participant.user_id] = participant.display_name
    if (user) names[user.id] = user.display_name
    return names
  }, [onlineUsers, user])

  const typingDisplay = typingUsers.map((id) => userNames[id] ?? id.slice(0, 8))
  if (isLLMThinking && !isLLMStreaming) typingDisplay.push('Claude')

  const participants = [
    { id: 'claude', name: 'Claude', isOnline: true, isClaude: true },
    ...onlineUsers.map((participant) => ({
      id: participant.user_id,
      name: participant.display_name,
      isOnline: participant.status === 'online',
      isClaude: false,
    })),
  ]

  if (!user || !currentRoom || !roomToken) return null

  return (
    <>
      <AppLayout
        sidebar={
          <RoomList
            rooms={rooms}
            activeRoomId={currentRoom.id}
            onRoomSelect={(id) => void switchRoom(id)}
            onCreateRoom={leaveRoom}
            userName={user.display_name}
            onLogout={handleLogout}
          />
        }
        main={
          <>
            <RoomHeader
              roomName={currentRoom.name ?? 'Dialectic'}
              threads={threads}
              activeThreadId={currentThread?.id ?? ''}
              onThreadChange={(id) => {
                const thread = threads.find((candidate) => candidate.id === id)
                if (thread) setThread(thread)
              }}
              onProtocolClick={() => setShowProtocolPicker(true)}
              onSettingsClick={() => setShowSettings(true)}
              connected={isConnected}
            />
            <ParticipantsBar participants={participants} />
            <RoomBriefing key={currentRoom.id} roomId={currentRoom.id} />
            {activeProtocol && (
              <ProtocolBanner
                protocol={activeProtocol}
                onAdvance={advanceProtocol}
                onAbort={abortProtocol}
              />
            )}
            <CommitmentSurface />
            <MessageList
              messages={displayMessages}
              currentUserId={user.id}
              onFork={forkFromMessage}
              streamingMessageId={isLLMStreaming ? STREAMING_ID : null}
              userNames={userNames}
            />
            <TypingIndicator typingUsers={typingDisplay} />
            <MessageInput
              onSend={(content, messageType) => sendMessage(content, messageType)}
              onTypingStart={sendTypingStart}
              onTypingStop={sendTypingStop}
              onTypingContent={sendTypingContent}
              disabled={!isConnected || !currentThread}
            />
          </>
        }
        rightPanel={
          <RightPanel
            memories={memories}
            threads={threads}
            activeThreadId={currentThread?.id ?? null}
            onThreadSelect={(id) => {
              const thread = threads.find((candidate) => candidate.id === id)
              if (thread) setThread(thread)
            }}
            onForkThread={forkLatest}
            onAddMemory={(key, content) => {
              if (!send('add_memory', { key, content })) window.alert('Reconnect before adding memory.')
            }}
            roomId={currentRoom.id}
            roomToken={roomToken}
            users={onlineUsers.map((participant) => ({
              id: participant.user_id,
              name: participant.display_name,
              status: participant.status,
            }))}
            onCreateCommitment={createCommitment}
            onUpdateConfidence={(commitmentId, confidence) => recordConfidence(commitmentId, confidence)}
            onResolveCommitment={handleResolveCommitment}
          />
        }
      />

      {showProtocolPicker && (
        <ProtocolPicker
          onInvoke={invokeProtocol}
          onClose={() => setShowProtocolPicker(false)}
        />
      )}
      {showSettings && (
        <RoomSettingsDialog
          roomId={currentRoom.id}
          onClose={() => setShowSettings(false)}
        />
      )}
    </>
  )
}

function App() {
  const isAuthenticated = useAppStore((s) => s.isAuthenticated)
  const currentRoom = useAppStore((s) => s.currentRoom)
  const accessToken = useAppStore((s) => s.accessToken)
  const refreshToken = useAppStore((s) => s.refreshToken)
  const user = useAppStore((s) => s.user)
  const setUser = useAppStore((s) => s.setUser)
  const logout = useAppStore((s) => s.logout)
  const refreshInFlight = useRef<string | null>(null)

  // Zustand restores this token from local storage, but the API client is not
  // persisted. Rehydrate it before either room screen performs a request.
  api.setAccessToken(accessToken ?? '')

  // Access JWTs are deliberately short-lived. Refresh shortly before expiry so
  // reconnects and saved-room access keep working during long thinking sessions.
  useEffect(() => {
    if (!isAuthenticated || !refreshToken || !user) return

    const expiry = accessTokenExpiry(accessToken)
    const delay = Math.max(0, expiry - Date.now() - 30_000)
    const timer = window.setTimeout(() => {
      if (refreshInFlight.current === refreshToken) return
      refreshInFlight.current = refreshToken
      api.refreshSession(refreshToken)
        .then((result) => {
          const tokens = result as { access_token: string; refresh_token: string }
          api.setAccessToken(tokens.access_token)
          setUser(user, tokens.access_token, tokens.refresh_token)
        })
        // The server explains revocations it knows the cause of (evicted by a
        // login on another device, password change). Carry that through to the
        // auth screen instead of dropping the user at a blank sign-in form.
        .catch((err: unknown) => logout(err instanceof Error ? err.message : undefined))
        .finally(() => {
          refreshInFlight.current = null
        })
    }, delay)

    return () => window.clearTimeout(timer)
  }, [isAuthenticated, accessToken, refreshToken, user, setUser, logout])

  if (!isAuthenticated) return <AuthScreen />
  if (!currentRoom) return <RoomSelector />
  return <ChatLayout />
}

export default App
