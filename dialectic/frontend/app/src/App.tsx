import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './styles/global.css'
import { useAppStore } from './stores/appStore.ts'
import { api } from './lib/api.ts'
import { AuthScreen } from './components/auth/AuthScreen.tsx'
import { RoomSelector } from './components/auth/RoomSelector.tsx'
import { RoomAccess } from './components/auth/RoomAccess.tsx'
import { useDialecticSocket } from './hooks/useDialecticSocket.ts'
import { useRoomNavigation, type RoomNavigation } from './hooks/useRoomNavigation.ts'
import { useDocumentVisibility } from './hooks/useDocumentVisibility.ts'
import { useAwayAlerts } from './hooks/useAwayAlerts.ts'
import { usePushSubscription } from './hooks/usePushSubscription.ts'
import type { Message, SearchResult, Thread, ThreadNode, TradingSnapshot } from './types/index.ts'
import { AppLayout } from './components/layout/AppLayout'
import { RoomHeader } from './components/layout/RoomHeader'
import { RoomSettingsDialog } from './components/layout/RoomSettingsDialog'
import { HelpDialog } from './components/layout/HelpDialog'
import { RoomList } from './components/sidebar/RoomList'
import { RightPanel } from './components/sidebar/RightPanel'
import { MessageList } from './components/chat/MessageList'
import { MessageInput } from './components/chat/MessageInput'
import { SearchOverlay } from './components/chat/SearchOverlay'
import { ParticipantsBar } from './components/chat/ParticipantsBar'
import { TypingIndicator } from './components/chat/TypingIndicator'
import { ProtocolPicker } from './components/protocols/ProtocolPicker'
import { ProtocolBanner } from './components/protocols/ProtocolBanner'
import { HomeActivityPulse } from './components/home/HomeActivityPulse'
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

function ChatLayout({ nav }: { nav: RoomNavigation }) {
  const user = useAppStore((s) => s.user)
  const accessToken = useAppStore((s) => s.accessToken)
  const refreshToken = useAppStore((s) => s.refreshToken)
  const currentRoom = useAppStore((s) => s.currentRoom)
  const currentThread = useAppStore((s) => s.currentThread)
  const threads = useAppStore((s) => s.threads)
  const messages = useAppStore((s) => s.messages)
  const memories = useAppStore((s) => s.memories)
  const reactions = useAppStore((s) => s.reactions)
  const attachments = useAppStore((s) => s.attachments)
  const typingUsers = useAppStore((s) => s.typingUsers)
  const onlineUsers = useAppStore((s) => s.onlineUsers)
  const isLLMThinking = useAppStore((s) => s.isLLMThinking)
  const isLLMStreaming = useAppStore((s) => s.isLLMStreaming)
  const llmToolActivity = useAppStore((s) => s.llmToolActivity)
  const streamingContent = useAppStore((s) => s.streamingContent)
  const activeProtocol = useAppStore((s) => s.activeProtocol)
  const roomToken = useAppStore((s) => s.roomToken)
  const setMessages = useAppStore((s) => s.setMessages)
  const setMemories = useAppStore((s) => s.setMemories)
  const logout = useAppStore((s) => s.logout)
  const setTradingConfig = useAppStore((s) => s.setTradingConfig)

  // Every destination change goes through nav.navigate — no setRoom,
  // setThread, or leaveRoom call expresses a destination in this file.
  const { rooms, navigate } = nav
  const [showRoomAccess, setShowRoomAccess] = useState(false)
  const [showProtocolPicker, setShowProtocolPicker] = useState(false)
  // The fork tree behind both the rail's compact view and the Branches
  // panel. A failed read keeps the previous tree and offers Retry.
  const [genealogy, setGenealogy] = useState<ThreadNode[]>([])
  const [genealogyError, setGenealogyError] = useState(false)
  // Bumped when Home settings adds a member, so the pulse's displayed
  // intersection contracts immediately instead of on the next interval.
  const [homeRefreshVersion, setHomeRefreshVersion] = useState(0)
  const [showSettings, setShowSettings] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [replyToId, setReplyToId] = useState<string | null>(null)
  const [showSearch, setShowSearch] = useState(false)
  // The nonce makes a repeat jump to the same message a distinct value, so the
  // stream re-scrolls instead of ignoring an unchanged prop.
  const [jumpTarget, setJumpTarget] = useState<{ id: string; nonce: number } | null>(null)

  const handleLogout = useCallback(() => {
    if (refreshToken) void api.logoutSession(refreshToken).catch(() => undefined)
    logout()
  }, [refreshToken, logout])

  // Restore the persisted JWT into the API singleton after a page reload.
  api.setAccessToken(accessToken ?? '')
  if (roomToken) api.setRoomToken(roomToken)

  // The collaborator who created a branch lands in it immediately — via the
  // same navigation transaction as every other destination (push history).
  const handleOwnFork = useCallback((thread: Thread) => {
    const state = useAppStore.getState()
    if (state.currentRoom) {
      void navigate({ roomId: state.currentRoom.id, threadId: thread.id }, 'push')
    }
  }, [navigate])

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
    refreshMemories,
    refreshPresence,
    markMessageRead,
    editMessageContent,
    deleteMessage,
    toggleReaction,
    refreshReactions,
    refreshAttachments,
  } = useDialecticSocket({ onOwnFork: handleOwnFork })

  const isVisible = useDocumentVisibility()
  const { state: pushState, enable: enablePush } = usePushSubscription(true)

  // Cmd/Ctrl+K is the near-universal "search this thing" gesture.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setShowSearch(true)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  // Asked once, on entering a room — which is always downstream of a click, so
  // the prompt is allowed. A refusal is respected permanently; the title badge
  // in useAwayAlerts still carries the signal without it.
  useEffect(() => {
    if (typeof Notification === 'undefined') return
    if (Notification.permission !== 'default') return
    void Notification.requestPermission().catch(() => undefined)
  }, [])

  // Read receipts are the source of truth for every unread badge, so each
  // message needs reporting exactly once — a resend on every render would be a
  // write per frame.
  const reportedReadRef = useRef<Set<string>>(new Set())
  const handleSeen = useCallback((messageId: string) => {
    if (reportedReadRef.current.has(messageId)) return
    if (!markMessageRead(messageId)) return
    reportedReadRef.current.add(messageId)
  }, [markMessageRead])

  // Hydrate collaboration state that is not delivered by the socket
  // handshake. Threads, room list, revocation fallback, and branch
  // selection all belong to useRoomNavigation now — navigate has already
  // installed a definitive room, token, and thread before this mounts.
  useEffect(() => {
    if (!currentRoom || !roomToken) return
    api.setRoomToken(roomToken)
    void refreshMemories()
    void refreshPresence()
  }, [currentRoom, roomToken, refreshMemories, refreshPresence])

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
        // Attachments are not projected onto messages, so the media a branch
        // carries has to be read separately. This is the exact fill — the live
        // probe in the socket hook only covers what arrives while connected.
        void refreshAttachments()
      })
      .catch((error) => console.error('Failed to load message history:', error))
    // Live reaction_updated events only cover changes made while connected, so
    // the existing set has to be fetched alongside the history.
    void refreshReactions()
  }, [currentThread, roomToken, setMessages, refreshReactions, refreshAttachments])

  // Genealogy refreshes when the room changes and when `threads` gains a
  // fork (refreshThreads updates it on every thread_created/forked event).
  const loadGenealogy = useCallback(() => {
    if (!currentRoom || !roomToken) return
    api.setRoomToken(roomToken)
    api.getGenealogy(currentRoom.id)
      .then((tree) => {
        setGenealogy(tree)
        setGenealogyError(false)
      })
      .catch((error) => {
        console.error('Failed to load genealogy:', error)
        setGenealogyError(true)
      })
  }, [currentRoom, roomToken])
  useEffect(() => {
    loadGenealogy()
  }, [loadGenealogy, threads])

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

  // Jumping to a search hit. Done entirely in this handler rather than through
  // an effect so the whole sequence stays in one place.
  //
  // Two cases: a hit in another branch just switches to it and lets that
  // branch's normal loader run; a hit in the current branch that is older than
  // the loaded window pulls a context window around it. Fetching a context
  // window while a thread switch is also loading would race two writers on the
  // same message list, which is why the two paths are kept apart.
  const handleJumpToResult = useCallback(async (result: SearchResult) => {
    setShowSearch(false)
    const isCurrentThread = currentThread?.id === result.thread_id

    if (!isCurrentThread) {
      if (currentRoom) {
        await navigate(
          { roomId: currentRoom.id, threadId: result.thread_id }, 'push',
        )
      }
    } else if (!messages.some((message) => message.id === result.id)) {
      try {
        api.setRoomToken(roomToken ?? '')
        const contextWindow = await api.getMessageContext(result.thread_id, result.id)
        if (Array.isArray(contextWindow)) {
          setMessages(contextWindow as Message[])
          // This path replaces the whole message list without going through the
          // history effect, so it owns its own attachment fill.
          void refreshAttachments()
        }
      } catch (error) {
        console.error('Failed to load message context:', error)
      }
    }

    setJumpTarget({ id: result.id, nonce: Date.now() })
  }, [currentRoom, currentThread?.id, messages, roomToken, navigate, setMessages, refreshAttachments])

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

  // A reply target belongs to the branch it was written in. Rather than clearing
  // it from an effect on thread change, resolve it against the messages actually
  // on screen: switching branches replaces `messages`, so a target from the old
  // branch stops resolving and both the preview and the outgoing reference fall
  // away on their own.
  const replyTarget = useMemo(() => {
    if (!replyToId) return null
    const target = messages.find((message) => message.id === replyToId)
    if (!target) return null
    const author = target.speaker_type === 'human'
      ? (target.user_name ?? (target.user_id ? userNames[target.user_id] : null) ?? 'Human')
      : 'Claude'
    return { author, content: target.content }
  }, [replyToId, messages, userNames])

  // Never send a reference to a message the composer can no longer resolve.
  const effectiveReplyToId = replyTarget ? replyToId : null

  // The "new since you were last here" boundary, taken from the same receipt
  // data the unread badge is computed from so the line and the badge can never
  // disagree.
  //
  // This is stable in practice rather than by construction: `rooms` is only
  // refetched when the room, room token, or access token changes, so the value
  // does not move as receipts are sent while reading. An access-token refresh
  // mid-session will re-fetch and drop the line, which is acceptable — by then
  // the messages under it have been read anyway.
  const roomMeta = rooms.find((room) => room.id === currentRoom?.id)
  const unreadSince = roomMeta?.last_read_at ?? roomMeta?.joined_at ?? null
  // Home derives from the saved-room descriptor, never from name or URL.
  const isHome = roomMeta?.is_home ?? currentRoom?.is_home === true

  useAwayAlerts({
    messages,
    currentUserId: user?.id ?? null,
    roomName: currentRoom?.name ?? 'Dialectic',
    isAway: !isVisible,
    streamingMessageId: isLLMStreaming ? STREAMING_ID : null,
    // With a live push subscription the service worker owns OS notifications.
    suppressNotifications: pushState === 'subscribed',
  })

  const typingDisplay = typingUsers.map((id) => userNames[id] ?? id.slice(0, 8))
  if (isLLMThinking && !isLLMStreaming) typingDisplay.push('Claude')

  // Only a tool that is still running says anything useful — a finished one is
  // already answered in the tokens arriving underneath it.
  const latestToolActivity = currentThread ? llmToolActivity[currentThread.id]?.at(-1) : undefined
  const toolActivityLabel = (isLLMThinking || isLLMStreaming) && latestToolActivity?.status === 'started'
    ? latestToolActivity.label
    : null

  const participants = [
    { id: 'claude', name: 'Claude', isOnline: true, isClaude: true },
    ...onlineUsers.map((participant) => ({
      id: participant.user_id,
      name: participant.display_name,
      isOnline: participant.status === 'online',
      isClaude: false,
      status: participant.status,
      lastSeen: participant.last_heartbeat,
    })),
  ]

  if (!user || !currentRoom || !roomToken) return null

  return (
    <>
      <AppLayout
        isHome={isHome}
        sidebar={
          <RoomList
            rooms={rooms}
            activeRoomId={currentRoom.id}
            onRoomSelect={(id) => void navigate({ roomId: id }, 'push')}
            onCreateRoom={() => setShowRoomAccess(true)}
            userName={user.display_name}
            onLogout={handleLogout}
            genealogy={genealogy}
            activeThreadId={currentThread?.id ?? null}
            onThreadSelect={(id) => {
              void navigate({ roomId: currentRoom.id, threadId: id }, 'push')
            }}
          />
        }
        main={
          <>
            <RoomHeader
              roomName={currentRoom.name ?? 'Dialectic'}
              threads={threads}
              activeThreadId={currentThread?.id ?? ''}
              onThreadChange={(id) => {
                void navigate({ roomId: currentRoom.id, threadId: id }, 'push')
              }}
              onProtocolClick={() => setShowProtocolPicker(true)}
              onSettingsClick={() => setShowSettings(true)}
              onSearchClick={() => setShowSearch(true)}
              onHelpClick={() => setShowHelp(true)}
              connected={isConnected}
              isHome={isHome}
              onHomeClick={() => void navigate({ roomId: null }, 'push')}
            />
            {!isHome && <ParticipantsBar participants={participants} />}
            {pushState === 'prompt' && typeof Notification !== 'undefined' && Notification.permission === 'default' && (
              <button className="push-enable-chip" onClick={enablePush}>
                🔔 Enable notifications — get buzzed when {participants.length > 2 ? 'the others' : 'the other person'} writes
              </button>
            )}
            {nav.accessError && (
              <div className="room-error">
                {nav.accessError}
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={nav.clearAccessError}
                  aria-label="Dismiss"
                >
                  ×
                </button>
              </div>
            )}
            {isHome && (
              <HomeActivityPulse
                onNavigate={(destination) => navigate(destination, 'push')}
                refreshVersion={homeRefreshVersion}
                residents={participants}
              />
            )}
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
              // Remount per branch so follow-the-tail and the unread pill start
              // fresh instead of inheriting the previous branch's scroll state.
              key={currentThread?.id ?? 'no-thread'}
              messages={displayMessages}
              currentUserId={user.id}
              onFork={forkFromMessage}
              onReply={(messageId) => {
                // The in-flight stream is a synthetic placeholder with no row in
                // the database, so it cannot be a reply target.
                if (messageId === STREAMING_ID) return
                setReplyToId(messageId)
              }}
              streamingMessageId={isLLMStreaming ? STREAMING_ID : null}
              userNames={userNames}
              unreadSince={unreadSince}
              onSeen={handleSeen}
              jumpTarget={jumpTarget}
              reactions={reactions}
              attachments={attachments}
              onToggleReaction={toggleReaction}
              onEditMessage={editMessageContent}
              onDeleteMessage={deleteMessage}
              emptyKind={isHome ? 'hearth' : 'dialogue'}
            />
            <TypingIndicator typingUsers={typingDisplay} activityLabel={toolActivityLabel} />
            <MessageInput
              roomId={currentRoom.id}
              onSend={(content, messageType, files) => {
                // The ids travel with the send itself: the server binds them in
                // the message transaction and the broadcast carries them back.
                const sent = sendMessage(
                  content,
                  messageType,
                  effectiveReplyToId,
                  files.map((file) => file.id),
                )
                if (!sent) return false
                setReplyToId(null)
                return true
              }}
              onTypingStart={sendTypingStart}
              onTypingStop={sendTypingStop}
              onTypingContent={sendTypingContent}
              disabled={!isConnected || !currentThread}
              replyTo={replyTarget}
              onCancelReply={() => setReplyToId(null)}
              placeholder={isHome ? 'Sit down — Claude is already here' : undefined}
              quiet={isHome}
            />
          </>
        }
        rightPanel={
          <RightPanel
            memories={memories}
            genealogy={genealogy}
            genealogyError={genealogyError}
            onRetryGenealogy={loadGenealogy}
            activeThreadId={currentThread?.id ?? null}
            onThreadSelect={(id) => {
              void navigate({ roomId: currentRoom.id, threadId: id }, 'push')
            }}
            onForkThread={forkLatest}
            onAddMemory={(key, content) => {
              if (!send('add_memory', { key, content })) window.alert('Reconnect before adding memory.')
            }}
            onSetMemoryPromotion={async (memoryId, promoted) => {
              const result = promoted
                ? await api.promoteMemory(memoryId)
                : await api.demoteMemory(memoryId)
              setMemories(memories.map((memory) => (
                memory.id === result.memory_id
                  ? { ...memory, personally_promoted: result.promoted }
                  : memory
              )))
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
            isHome={isHome}
            canManageHome={roomMeta?.can_manage_home ?? false}
            onMembershipChanged={() => setHomeRefreshVersion((version) => version + 1)}
          />
        }
      />

      {showSearch && (
        <SearchOverlay
          roomId={currentRoom.id}
          onClose={() => setShowSearch(false)}
          onJump={(result) => { void handleJumpToResult(result) }}
        />
      )}
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
      {showHelp && (
        <HelpDialog onClose={() => setShowHelp(false)} />
      )}
      {showRoomAccess && (
        <RoomAccess
          mode="dialog"
          rooms={rooms}
          onRoomSelect={async (destination) => {
            const entered = await navigate(destination, 'push')
            if (entered) setShowRoomAccess(false)
            return entered
          }}
          onRoomGranted={async (granted) => {
            const entered = await nav.enterGrantedRoom(granted)
            if (entered) setShowRoomAccess(false)
            return entered
          }}
          onClose={() => setShowRoomAccess(false)}
        />
      )}
    </>
  )
}

/**
 * Owns the navigation hook. ChatLayout — and with it the socket and every
 * room-scoped hydration effect — does not mount until navigate has
 * installed a definitive room, token, and thread, so a bare URL resolving
 * to Home can never open a socket for the persisted room. The guest
 * invite path (no access token, no room) lands on the full selector and
 * never calls the Home activity endpoint.
 */
function AuthenticatedWorkspace() {
  const nav = useRoomNavigation()
  const currentRoom = useAppStore((s) => s.currentRoom)
  const roomToken = useAppStore((s) => s.roomToken)

  if (!nav.ready) {
    return (
      <div className="room-screen">
        <div className="room-card">
          <p className="room-empty">Loading your rooms…</p>
        </div>
      </div>
    )
  }
  if (!currentRoom || !roomToken) return <RoomSelector nav={nav} />
  return <ChatLayout nav={nav} />
}

function App() {
  const isAuthenticated = useAppStore((s) => s.isAuthenticated)
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
  return <AuthenticatedWorkspace />
}

export default App
