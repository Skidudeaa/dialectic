import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { PARTICIPANT_NAME } from './lib/productIdentity.ts'
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
import type { Message, SearchResult, ThesisSeed, Thread, ThreadNode, TradingSnapshot } from './types/index.ts'
import { AppLayout } from './components/layout/AppLayout'
import { RoomHeader } from './components/layout/RoomHeader'
import { RoomSettingsDialog } from './components/layout/RoomSettingsDialog'
import { HelpDialog, type HelpTab } from './components/layout/HelpDialog'
import { RoomList } from './components/sidebar/RoomList'
import { RightPanel } from './components/sidebar/RightPanel'
import { MemoryPanel } from './components/sidebar/MemoryPanel'
import { MessageList } from './components/chat/MessageList'
import { MessageInput } from './components/chat/MessageInput'
import { SearchOverlay } from './components/chat/SearchOverlay'
import { ParticipantsBar } from './components/chat/ParticipantsBar'
import { TypingIndicator } from './components/chat/TypingIndicator'
import { ProtocolPicker } from './components/protocols/ProtocolPicker'
import { ProtocolBanner } from './components/protocols/ProtocolBanner'
import { HomeActivityPulse } from './components/home/HomeActivityPulse'
import { ProposalInbox } from './components/home/ProposalInbox'
import { BriefingPanel } from './components/analytics/BriefingPanel'
import { CommitmentSurface } from './components/stakes/CommitmentSurface'
import { WorkspaceSceneFrame } from './components/workspace/WorkspaceSceneFrame'
import { BenchScene } from './components/workspace/scenes/BenchScene'
import { LibraryScene } from './components/workspace/scenes/LibraryScene'
import { LedgerScene } from './components/workspace/scenes/LedgerScene'
import { FieldScene } from './components/workspace/scenes/FieldScene'
import { AtlasScene } from './components/workspace/scenes/AtlasScene'
import { MirrorPanel } from './components/workspace/MirrorPanel'
import { FocusSurface } from './components/workspace/focus/FocusSurface.tsx'
import { bareMarkId } from './components/workspace/fieldDisplay.ts'
import { TradingPanel } from './components/trading/TradingPanel'
import { sceneAfterFocusNavigate, scenesForDestination } from './lib/workspaceRoute.ts'
import { useWorkspaceObjects } from './hooks/useWorkspaceObjects.ts'
import { useFieldMarks } from './hooks/useFieldMarks.ts'
import { useAtlas } from './hooks/useAtlas.ts'
import { useGeoScopes } from './hooks/useGeoScopes.ts'
import { useTradingDesk } from './hooks/useTradingDesk.ts'
import { Console } from './components/workspace/Console'
import type { SceneSignal } from './components/workspace/SceneSwitcher'
import type { ImplementedWorkspaceScene } from './types/index.ts'
import type { FieldMark, FieldReviewRequest } from './types/workspace.ts'
import { rememberSceneAxes, restoreSceneAxes } from './lib/sceneContinuity.ts'
import {
  decodeWorldView,
  encodeWorldView,
  isWorldView,
} from './components/workspace/world/worldCamera.ts'

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

export function ChatLayout({ nav }: { nav: RoomNavigation }) {
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
  const [roomMembers, setRoomMembers] = useState<{ user_id: string; display_name: string }[]>([])
  const isLLMThinking = useAppStore((s) => s.isLLMThinking)
  const isLLMStreaming = useAppStore((s) => s.isLLMStreaming)
  const isDeepDiveActive = useAppStore((s) => s.isDeepDiveActive)
  const workspaceScene = useAppStore((s) => s.workspaceScene)
  const llmToolActivity = useAppStore((s) => s.llmToolActivity)
  const streamingContent = useAppStore((s) => s.streamingContent)
  const activeProtocol = useAppStore((s) => s.activeProtocol)
  const roomToken = useAppStore((s) => s.roomToken)
  const setMessages = useAppStore((s) => s.setMessages)
  const setMemories = useAppStore((s) => s.setMemories)
  const logout = useAppStore((s) => s.logout)
  const setTradingConfig = useAppStore((s) => s.setTradingConfig)
  const tradingConfig = useAppStore((s) => s.tradingConfig)

  // Exact-restoration axes (§15.2, TG-E) that are not part of a destination —
  // homed in appStore (see its own header comment), reset per-room there.
  // No surface writes these yet; they exist so continuity has a real slot to
  // capture and a future consumer never has to touch sceneContinuity.ts
  // again to use them.
  const focusMode = useAppStore((s) => s.focusMode)
  const inspectorTab = useAppStore((s) => s.inspectorTab)
  const fieldViewport = useAppStore((s) => s.fieldViewport)
  const recordScroll = useAppStore((s) => s.recordScroll)
  const openProposal = useAppStore((s) => s.openProposal)
  const setFocusMode = useAppStore((s) => s.setFocusMode)
  const setInspectorTab = useAppStore((s) => s.setInspectorTab)
  const setFieldViewport = useAppStore((s) => s.setFieldViewport)
  const setRecordScroll = useAppStore((s) => s.setRecordScroll)
  const setOpenProposal = useAppStore((s) => s.setOpenProposal)

  // Every destination change goes through nav.navigate — no setRoom,
  // setThread, or leaveRoom call expresses a destination in this file.
  const { rooms, navigate, objectId, viewId } = nav
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
  // null = closed. A tab rather than a boolean because the header's unread
  // badge opens straight onto "What changed": a badge that opens a dialog
  // showing something else is a badge that lies about what it counts.
  const [helpTab, setHelpTab] = useState<HelpTab | null>(null)
  // Lazy initializers, not an effect: both restore from continuity exactly
  // once, on ChatLayout's first render for this window — reading storage
  // synchronously during an effect body to call setState would cascade an
  // extra render (react-hooks/set-state-in-effect) for no benefit, since the
  // value is already known before the first paint. replyToId is reconciled
  // for free by replyTarget below, which resolves it against `messages` and
  // silently drops it the instant it does not resolve (§15.5).
  const [replyToId, setReplyToId] = useState<string | null>(
    () => restoreSceneAxes(user?.id ?? null)?.replyToId ?? null,
  )
  // The composer's unsent text. components/chat/MessageInput.tsx owns the
  // live textarea's `content` state (still local and uncontrolled — this is
  // NOT a fully controlled input); it accepts an `initialValue` prop, a
  // minimal easement granted to this task group specifically for restoration
  // (owner ruling, see PLAN.md §5.5 amendment), used only as MessageInput's
  // own `useState` initial value, so this seeds the textarea once on mount
  // and does not fight the user's typing on every later render. Also
  // captured here via the onTypingContent callback MessageInput already
  // calls on every keystroke, purely so continuity has the latest text to
  // remember — MessageInput remains the source of truth for what is
  // actually on screen after the first render.
  const [composerDraft, setComposerDraft] = useState(
    () => restoreSceneAxes(user?.id ?? null)?.composerDraft ?? '',
  )
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
    sendDeepDive,
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

  // Load exactly one persisted window for the installed destination. A push
  // target needs server context around that message; an ordinary destination
  // needs the latest branch history. The cancellation fence prevents a slower
  // previous destination from overwriting the room/thread reached afterward.
  useEffect(() => {
    if (!currentThread || !roomToken || !isVisible) return
    api.setRoomToken(roomToken)
    let cancelled = false
    const loadHistory = async () => {
      let targeted = false
      let data: { messages?: Message[] } | Message[]
      if (nav.messageId) {
        try {
          const context = await api.getMessageContext(
            currentThread.id, nav.messageId,
          )
          if (cancelled) return
          data = context as Message[]
          targeted = Array.isArray(context)
            && context.some((message) => message.id === nav.messageId)
          if (!targeted) {
            data = await api.getMessages(currentThread.id, 200) as (
              { messages?: Message[] } | Message[]
            )
          }
        } catch {
          if (cancelled) return
          data = await api.getMessages(currentThread.id, 200) as (
            { messages?: Message[] } | Message[]
          )
        }
      } else {
        data = await api.getMessages(currentThread.id, 200) as (
          { messages?: Message[] } | Message[]
        )
      }
      if (cancelled) return

      const history = Array.isArray(data) ? data : data.messages
      if (Array.isArray(history)) {
        setMessages(history)
        if (targeted && nav.messageId) {
          setJumpTarget({ id: nav.messageId, nonce: Date.now() })
        }
      }
      // Attachments are not projected onto messages, so the media a branch
      // carries has to be read separately. This is the exact fill — the live
      // probe in the socket hook only covers what arrives while connected.
      await Promise.all([
        refreshAttachments(currentThread.id),
        refreshReactions(currentThread.id),
      ])
    }
    void loadHistory().catch((error) => {
      if (!cancelled) console.error('Failed to load message history:', error)
    })
    return () => { cancelled = true }
    // `isVisible` is a dependency because a push is only ever SENT to someone
    // with no live socket to the room — so a pushed message was never
    // delivered over the wire and exists only server-side. Nothing else
    // backfills it: the socket replays no history on reconnect, and a tap
    // back into the room the app is already in moves none of the other deps.
    // Waking up is therefore the only reliable moment to re-read the branch.
  }, [
    currentThread, roomToken, nav.messageId, isVisible, setMessages,
    refreshReactions, refreshAttachments,
  ])

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

  // Who belongs to this room. Presence arrives over the socket; MEMBERSHIP
  // does not, and the @-picker needs the member who has not spoken yet.
  useEffect(() => {
    if (!currentRoom || !roomToken) return
    api.setRoomToken(roomToken)
    let cancelled = false
    api.getRoomMembers(currentRoom.id)
      .then((members) => { if (!cancelled) setRoomMembers(members) })
      // A roster that fails to load degrades the picker to whoever is online
      // and whoever has spoken — never blocks the composer.
      .catch(() => { if (!cancelled) setRoomMembers([]) })
    return () => { cancelled = true }
  }, [currentRoom, roomToken])

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
    // Membership first, presence over the top — a member who has never
    // spoken and is not connected still has a name worth knowing.
    for (const member of roomMembers) names[member.user_id] = member.display_name
    for (const participant of onlineUsers) names[participant.user_id] = participant.display_name
    if (user) names[user.id] = user.display_name
    return names
  }, [roomMembers, onlineUsers, user])

  const memberNames = useMemo(() => Object.values(userNames), [userNames])

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
      : PARTICIPANT_NAME
    return { author, content: target.content }
  }, [replyToId, messages, userNames])

  // Never send a reference to a message the composer can no longer resolve.
  const effectiveReplyToId = replyTarget ? replyToId : null

  // Restore this window's remaining non-destination axes (§15.2) into
  // appStore exactly once, when ChatLayout first mounts. By then nav.navigate
  // has already installed room/thread/scene/object for this boot —
  // including a restored object, via restoreScene's `object` field flowing
  // through useRoomNavigation's own boot effect, which this file does not
  // touch. ChatLayout is not remounted on later in-session room switches
  // (AuthenticatedWorkspace renders it unkeyed), so this genuinely fires
  // once per window life — "restoration", not "every room switch".
  // replyToId/composerDraft restore via the lazy useState initializers
  // above instead of here, to avoid the extra setState-in-effect render
  // this rule (react-hooks/set-state-in-effect) flags for a REACT-owned
  // setter; appStore's setters are a store method, not a React setState, so
  // they are exempt from that rule and stay here for a single, obvious
  // restoration hook.
  const restoredStoreAxesRef = useRef(false)
  useEffect(() => {
    if (restoredStoreAxesRef.current) return
    restoredStoreAxesRef.current = true
    const axes = restoreSceneAxes(user?.id ?? null)
    if (!axes) return
    setFocusMode(axes.focusMode)
    setInspectorTab(axes.inspectorTab)
    setFieldViewport(axes.fieldViewport)
    setRecordScroll(axes.recordScroll)
    setOpenProposal(axes.openProposal)
  }, [
    user?.id, setFocusMode, setInspectorTab, setFieldViewport,
    setRecordScroll, setOpenProposal,
  ])

  // The write side: merge-patch every v2 axis into continuity's own storage
  // whenever one changes. `objectId` is captured here rather than at its
  // source (useRoomNavigation.ts) because that file is the ONE destination
  // writer and is explicitly out of this task group's reach — mirroring its
  // value through this effect keeps that boundary intact while still
  // letting continuity remember it (see sceneContinuity.ts's own header for
  // why this is a second WRITE path into storage, not a second destination
  // writer). rememberSceneAxes no-ops before the first navigate has ever
  // written a record, so this is safe to run from the first render.
  useEffect(() => {
    rememberSceneAxes(user?.id ?? null, {
      objectId, replyToId, composerDraft,
      focusMode, inspectorTab, fieldViewport, recordScroll, openProposal,
    })
  }, [
    user?.id, objectId, replyToId, composerDraft,
    focusMode, inspectorTab, fieldViewport, recordScroll, openProposal,
  ])

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
  // Only Home's ROOT carries the household; a Home branch is an ordinary
  // conversation. That rule now lives in scenesForDestination, which the frame
  // and the router share, rather than in a local flag read by one of them.
  // One projection per room, filtered per scene — the server builds every kind
  // in a single pass regardless, so asking once per scene would be four full
  // projections to render one room.
  //
  // Disabled at Home (which offers no workroom scene) and for a guest identity,
  // which holds no JWT: the projection sits behind get_current_user, so firing
  // the request anyway would paint "unavailable" across every scene and read as
  // an outage rather than as the guest boundary it is.
  const workspaceObjects = useWorkspaceObjects(
    currentRoom?.id ?? null,
    Boolean(accessToken) && !isHome,
  )
  // Same fence as workspaceObjects, for the same reasons — the Field sits
  // behind get_current_user too, and Home holds no Field (§5.2). Fetched
  // unconditionally (not only while the Field scene is showing): Focus can
  // open from Bench/Library/Ledger too, and FocusStructure's "incoming"
  // relationships need the room's marks regardless of which scene tapped
  // the object that opened it.
  const fieldMarks = useFieldMarks(
    currentRoom?.id ?? null,
    Boolean(accessToken) && !isHome,
  )
  // Atlas remains a JWT-only cross-room projection, but Synapse lets its
  // House/World embodiments stay inside an ordinary room. Fetch it only when
  // one of those causal surfaces actually consumes it: Home, Atlas, Field, or
  // a causal Focus object. Ordinary Record sessions still pay no Atlas read.
  const causalObjectSelected = Boolean(
    objectId?.startsWith('geo_scope:') || objectId?.startsWith('field_mark:'),
  )
  const atlas = useAtlas(Boolean(accessToken) && (
    isHome
    || workspaceScene === 'atlas'
    || workspaceScene === 'field'
    || causalObjectSelected
  ))
  const causalBindings = atlas.status === 'ready'
    ? (atlas.projection.causal_bindings ?? [])
    : []
  // Capabilities follow the exact room IDs the already-fenced signal
  // projection carries, then resolve against the complete saved-room list.
  // This stays bounded by Atlas rather than by the rail's activity ordering;
  // tokens never enter the Atlas wire response or a URL/body.
  const signalRoomTokens = useMemo<ReadonlyMap<string, string> | undefined>(() => {
    if (atlas.status !== 'ready') return undefined
    const signalRoomIds = new Set(
      (atlas.projection.signals ?? []).map((signal) => signal.room_id),
    )
    return new Map(
      rooms
        .filter((room) => room.token && signalRoomIds.has(room.id))
        .map((room) => [room.id, room.token]),
    )
  }, [atlas, rooms])
  // The room's own geography (World Lens) — read only to decide whether the
  // Bench offers its World door; the globe itself lives at Home root.
  const roomGeo = useGeoScopes(!isHome && accessToken ? currentRoom?.id ?? null : null)

  // The ONE trading-desk instance, lifted from BenchScene so the Console's
  // instrument tiles stay live in every scene. An unbound room short-circuits
  // at the 409 structure probe (one request); Home mounts none at all.
  // ponytail: entering a bound room now runs the full fan-out + 300s quote
  // poll outside the Bench too — that IS the Console's job; a slice-keys
  // filter on the hook is the upgrade path if it ever matters.
  const desk = useTradingDesk(!isHome && currentRoom ? currentRoom.id : null)

  // Docky running-dot signals for the scene tiles. Record's baseline is
  // "messages seen when the Record was last showing" — MessageList's own
  // missedCount is deliberately local to it, so the tray derives its own.
  const recordSeenRef = useRef(0)
  const onRecordSurface = workspaceScene === 'record' || workspaceScene === 'house'
  useEffect(() => {
    if (onRecordSurface) recordSeenRef.current = messages.length
  }, [onRecordSurface, messages.length])
  // Room switch resets the scene to the default (record/house) via setRoom,
  // so the baseline re-anchors before any badge can carry across rooms.
  const sceneSignals = useMemo<Partial<Record<ImplementedWorkspaceScene, SceneSignal>>>(() => {
    const signals: Partial<Record<ImplementedWorkspaceScene, SceneSignal>> = {}
    const recordNew = onRecordSurface ? 0 : Math.max(0, messages.length - recordSeenRef.current)
    if (recordNew > 0) signals.record = { count: recordNew, tone: 'teal' }
    const alerts = tradingConfig?.alertEvents ?? []
    if (alerts.length > 0 && workspaceScene !== 'bench') {
      const worst = alerts.some((a) => a.severity === 'critical') ? 'red' : 'amber'
      signals.bench = { count: alerts.length, tone: worst }
    }
    if (fieldMarks.status === 'ready' && workspaceScene !== 'field') {
      const pending = fieldMarks.marks.filter((mark) => mark.review === 'provisional').length
      if (pending > 0) signals.field = { count: pending, tone: 'amber' }
    }
    return signals
  }, [onRecordSurface, messages.length, tradingConfig, workspaceScene, fieldMarks])

  /**
   * The room's marks, indexed by the message each one points at, so the
   * transcript can show a mark beside the words it is about.
   *
   * A mark can name several subjects (claim_group, merges); it appears under
   * every message it names, because "this mark is about your sentence" is
   * true for each of them. No mark_kind filter is needed — FieldProjection
   * returns relation marks only, with reviews inline on each.
   */
  const marksByMessage = useMemo(() => {
    const index: Record<string, FieldMark[]> = {}
    if (fieldMarks.status !== 'ready') return index
    for (const mark of fieldMarks.marks) {
      for (const subject of mark.subjects) {
        if (subject.entity !== 'messages') continue
        ;(index[subject.id] ??= []).push(mark)
      }
    }
    return index
  }, [fieldMarks])

  const refreshField = useCallback(() => {
    if (fieldMarks.status === 'ready') fieldMarks.refresh()
  }, [fieldMarks])

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
  if (isLLMThinking && !isLLMStreaming) typingDisplay.push(PARTICIPANT_NAME)

  // Only a tool that is still running says anything useful — a finished one is
  // already answered in the tokens arriving underneath it.
  const latestToolActivity = currentThread ? llmToolActivity[currentThread.id]?.at(-1) : undefined
  const toolActivityLabel = (isLLMThinking || isLLMStreaming) && latestToolActivity?.status === 'started'
    ? latestToolActivity.label
    : null

  const participants = [
    // `isClaude` stays as the internal prop name this tranche; only the
    // visible label changes.
    { id: 'dialectic', name: PARTICIPANT_NAME, isOnline: true, isClaude: true },
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

  /**
   * Take a proposed thesis to the Bench where it can actually be created.
   *
   * Outside Home that is this room's own Bench and nothing moves. AT HOME
   * there is no Bench and `POST .../trading/thesis` answers 409 "Propose it in
   * the scheme's room" — so the tap used to resolve to the default scene and
   * do nothing at all. That silent refusal is what pushed general talk back
   * out of the shared room: the one place built so conversation would not get
   * lost in the individual threads could not turn a conversation into work.
   *
   * So Home spawns the scheme's room instead of naming it as somewhere to go.
   * The server carries Home's membership into it in the same statement that
   * creates it — `POST /rooms` writes none, which is why a bound trading room
   * with zero members already exists in production.
   *
   * ORDER IS LOAD-BEARING: appStore clears `thesisSeed` on room switch, on
   * purpose (a seed from the room you left means nothing in the one you
   * entered). Seeding before navigating would be dropped in flight, so the
   * seed is set only after `navigate` resolves. Do not move that write ahead
   * of navigation.
   */
  const openThesisSeed = async (seed: ThesisSeed) => {
    const store = useAppStore.getState()
    if (!isHome) {
      store.setThesisSeed(seed)
      void navigate({
        roomId: currentRoom.id,
        threadId: currentThread?.id ?? null,
        scene: 'bench',
      }, 'push')
      return
    }
    try {
      const spawned = await api.spawnScheme(seed.title)
      const arrived = await navigate({
        roomId: spawned.room_id,
        threadId: spawned.thread_id,
        scene: 'bench',
      }, 'push')
      // Only seed once we are actually there; a refused navigation would
      // otherwise leave a seed sitting in the room we never left.
      if (arrived) useAppStore.getState().setThesisSeed(seed)
    } catch (err) {
      window.alert(
        err instanceof Error
          ? `Could not open a room for this scheme: ${err.message}`
          : 'Could not open a room for this scheme.',
      )
    }
  }

  // WHY these are built AFTER the null guard above: each reads user.id,
  // currentRoom.id and roomToken, which are only non-null past that return.
  const recordSurface = (
    <>
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
            marksByMessage={marksByMessage}
            onFieldChanged={refreshField}
            unreadSince={unreadSince}
            onSeen={handleSeen}
            jumpTarget={jumpTarget}
            reactions={reactions}
            attachments={attachments}
            onToggleReaction={toggleReaction}
            onEditMessage={editMessageContent}
            onDeleteMessage={deleteMessage}
            emptyKind={isHome ? 'hearth' : 'dialogue'}
            onOpenBench={(seed) => { void openThesisSeed(seed) }}
          />
          <TypingIndicator typingUsers={typingDisplay} activityLabel={toolActivityLabel} />
          <MessageInput
            roomId={currentRoom.id}
            memberNames={memberNames}
            initialValue={composerDraft}
            onSend={(content, messageType, files, tags) => {
              // The ids travel with the send itself: the server binds them in
              // the message transaction and the broadcast carries them back.
              const sent = sendMessage(
                content,
                messageType,
                effectiveReplyToId,
                files.map((file) => file.id),
                tags,
              )
              if (!sent) return false
              setReplyToId(null)
              // The composer clears its own local `content` on a successful
              // send (MessageInput.tsx) — mirror that here so continuity
              // never restores a draft that was already sent.
              setComposerDraft('')
              return true
            }}
            onTypingStart={sendTypingStart}
            onTypingStop={sendTypingStop}
            onTypingContent={(content) => {
              sendTypingContent(content)
              // Captured for continuity only — see composerDraft's own
              // declaration above for why this does not feed back into the
              // textarea.
              setComposerDraft(content)
            }}
            onResearch={sendDeepDive}
            researchActive={isDeepDiveActive}
            disabled={!isConnected || !currentThread}
            replyTo={replyTarget}
            onCancelReply={() => setReplyToId(null)}
            placeholder={isHome ? `Sit down — ${PARTICIPANT_NAME} is already here` : undefined}
            quiet={isHome}
          />
    </>
  )

  // The House is the shipped pulse ABOVE the same table — the Record is not
  // duplicated into a second component, it is composed.
  //
  // AMENDED 2026-08-15: the pulse renders COMPACT here. It used to stack
  // residents, needs, movement and every scheme door ahead of the transcript,
  // which made the room the two of them share read as a directory pointing at
  // the other rooms. The conversation is the place; the pulse is the lintel
  // over it. Everything demoted is one <details> away, not gone.
  const houseSurface = (
    <>
      <HomeActivityPulse
        onNavigate={(destination) => navigate(destination, 'push')}
        refreshVersion={homeRefreshVersion}
        residents={participants}
        compact
      />
      <ProposalInbox onNavigate={(destination) => navigate(destination, 'push')} />
      {recordSurface}
    </>
  )

  // What this destination may show — the ONE definition, shared with the
  // router, so the switcher can never offer a scene a URL would be refused.
  const availableScenes = scenesForDestination(
    { is_home: isHome },
    { parent_thread_id: currentThread?.parent_thread_id ?? null },
  )

  // Every workroom scene is a filter over ONE projection of this room. The
  // scenes that need it are only reachable outside Home, and the projection
  // sits behind get_current_user, so a guest identity would 401 on every call —
  // hence the explicit enable rather than an unconditional fetch.
  // §1.18: a tap selects the object into Focus, product-wide — it no longer
  // jumps to the object's branch (Release 2's behavior). "Open branch" lives
  // inside Focus itself now (FocusSurface.tsx), as one of its actions rather
  // than the tap's only outcome. Selecting stays in the SAME room/thread/
  // scene, so the surface underneath does not jump around under the reader
  // just because they looked at something in it.
  //
  // Typed structurally ({ id: string }) rather than WorkspaceObject: the
  // Field scene passes a FieldMark here, which shares the same id space
  // (`field_mark:<uuid>`, same as every other workspace-object id) but is
  // NOT a WorkspaceObject — field marks are deliberately not wired into the
  // generic projection this release (§5.1).
  const openWorkspaceObject = (object: { id: string }) => {
    void navigate({
      roomId: currentRoom.id,
      threadId: currentThread?.id ?? null,
      scene: workspaceScene,
      object: object.id,
    }, 'push')
  }

  // FocusSurface's one navigation primitive (see its own doc comment for
  // why it is one function and not three) — resolved here, where roomId and
  // the current thread/scene are already in scope, so Focus itself never
  // has to reconstruct a destination from parts it was not given.
  const focusNavigate = (target: {
    threadId?: string
    messageId?: string
    object: string | null
    historyMode?: 'push' | 'replace'
  }) => {
    void navigate({
      roomId: currentRoom.id,
      threadId: target.threadId ?? currentThread?.id ?? null,
      scene: sceneAfterFocusNavigate(workspaceScene, target.threadId),
      object: target.object,
      messageId: target.messageId ?? null,
    }, target.historyMode ?? 'push')
  }

  // One destination writer joins both causal doors to the same World state.
  // The live current scope comes from the server projection; a Field mark may
  // remain the selected object while Atlas highlights that scope beneath it.
  const openWorldEvidence = (scopeObjectId: string, selectedObject = scopeObjectId) => {
    void navigate({
      roomId: currentRoom.id,
      threadId: null,
      scene: 'atlas',
      object: selectedObject,
      view: `world;room=${currentRoom.id}`,
    }, 'push')
  }

  const handleFieldReview = async (markId: string, request: FieldReviewRequest) => {
    await api.postFieldReview(currentRoom.id, bareMarkId(markId), request)
    if (fieldMarks.status === 'ready') fieldMarks.refresh()
    atlas.retry()
  }

  const sceneContent = {
    house: houseSurface,
    // Home root only. The Mirror is about the reader, not about a room --
    // and it is fenced in the SQL to `user_model:<caller>`, so there is no
    // room or user id to hand it and deliberately no way to ask for anyone
    // else's.
    mirror: <MirrorPanel />,
    atlas: (
      <AtlasScene
        state={atlas}
        view={viewId}
        selectedObjectId={objectId}
        signalRoomTokens={accessToken ? signalRoomTokens : undefined}
        // Atlas retry refreshes the combined live/durable projection. Queue a
        // room projection refresh too through the same loading-safe contract;
        // it remains dormant while Home has no room-local projection mounted.
        onGeoChanged={roomGeo.retry}
        // House/World mode and camera ride the URL's `view` axis and are
        // written only here. An ordinary room's first World tap acquires that
        // room as its focus; later camera replacements preserve it.
        onView={(view, mode) => {
          const decodedView = decodeWorldView(view)
          const nextView = !isHome && decodedView
            ? encodeWorldView({
                camera: decodedView.camera,
                roomId: currentRoom.id,
              })
            : view
          void navigate({
            roomId: currentRoom.id,
            threadId: null,
            scene: 'atlas',
            object: objectId,
            view: nextView,
          }, mode)
        }}
        onNavigate={(destination) => {
          // A branch is still a conversation destination. Every object and
          // room destination stays in Atlas so World does not disappear when
          // Focus opens. Room changes reset the prior camera and object.
          if (destination.threadId && !destination.object) {
            void navigate({
              roomId: destination.roomId,
              threadId: destination.threadId,
              object: null,
            }, 'push')
            return
          }
          const nextWorldView = isWorldView(viewId)
            ? `world;room=${destination.roomId}`
            : null
          void navigate({
            roomId: destination.roomId,
            threadId: null,
            scene: 'atlas',
            object: destination.object ?? null,
            messageId: destination.messageId ?? null,
            view: nextWorldView,
          }, 'push')
        }}
      />
    ),
    record: recordSurface,
    bench: (
      <BenchScene
        state={workspaceObjects}
        onOpen={openWorkspaceObject}
        tradingPanel={<TradingPanel />}
        roomId={currentRoom?.id ?? null}
        desk={desk}
        // World Lens: a room that owns geography gets one door onto Atlas /
        // World, prefocused on its own scopes. Absent otherwise — a globe on
        // every room regardless of whether geography matters is the vision's
        // own non-negotiable no.
        worldLink={
          roomGeo.status === 'ready' && roomGeo.projection.scopes.length > 0 && currentRoom ? (
            <button
              type="button"
              className="cockpit-world-link"
              onClick={() => {
                void navigate({
                  roomId: currentRoom.id,
                  threadId: null,
                  scene: 'atlas',
                  object: objectId,
                  view: `world;room=${currentRoom.id}`,
                }, 'push')
              }}
            >
              World ↗ <span className="cockpit-world-link-count">{roomGeo.projection.scopes.length} placed</span>
            </button>
          ) : null
        }
      />
    ),
    field: (
      <FieldScene
        state={fieldMarks}
        objects={workspaceObjects}
        onOpen={openWorkspaceObject}
        worldBindings={causalBindings}
        onOpenWorld={openWorldEvidence}
      />
    ),
    library: <LibraryScene state={workspaceObjects} onOpen={openWorkspaceObject} />,
    ledger: (
      <LedgerScene
        state={workspaceObjects}
        onOpen={openWorkspaceObject}
        // The panel travels WITH the scene. The Ledger shows what the room
        // holds; adding a fact and granting personal recall are still done
        // here, so moving the tab must not drop the affordances.
        memoryPanel={
          <MemoryPanel
            memories={memories}
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
          />
        }
      />
    ),
  }

  return (
    <>
      <AppLayout
        isHome={isHome}
        workspaceScene={workspaceScene}
        homeTalking={isHome && workspaceScene === 'house' && displayMessages.length > 0}
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
              onHelpClick={(tab) => setHelpTab(tab)}
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
            <div className="workspace-with-focus">
              <WorkspaceSceneFrame
                scene={workspaceScene}
                scenes={availableScenes}
                onSelect={(scene) => {
                  void navigate({
                    roomId: currentRoom.id,
                    threadId: currentThread?.id ?? null,
                    // Focus rides alongside whatever scene is showing (§5.2)
                    // — a scene switch does not close it.
                    scene,
                    object: objectId,
                  }, 'push')
                }}
                content={sceneContent}
                signals={sceneSignals}
                instruments={<Console desk={desk} />}
              />
              {/* Home holds no Field and offers no object-tap surface today
                  (§5.2) — Focus never opens there in practice, but the guard
                  is explicit rather than relying on that absence, since
                  `objects`/`fieldMarks` are not fetched at Home and a stray
                  `&object=` would otherwise hang in a permanent loading
                  state instead of resolving to "not here". */}
              {!isHome && objectId && (
                <FocusSurface
                  objectId={objectId}
                  objects={workspaceObjects}
                  fieldMarks={fieldMarks}
                  canAct={Boolean(accessToken)}
                  onNavigate={focusNavigate}
                  onReview={handleFieldReview}
                  roomId={currentRoom.id}
                  geo={roomGeo}
                  onGeoChanged={() => {
                    roomGeo.retry()
                    atlas.retry()
                  }}
                  onMarked={() => {
                    if (fieldMarks.status === 'ready') fieldMarks.refresh()
                    else if (fieldMarks.status === 'unavailable') fieldMarks.retry()
                    atlas.retry()
                  }}
                  worldBindings={causalBindings}
                  onOpenWorld={openWorldEvidence}
                />
              )}
            </div>
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
            scene={workspaceScene}
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
      {helpTab && (
        <HelpDialog
          roomId={currentRoom.id}
          initialTab={helpTab}
          onClose={() => setHelpTab(null)}
        />
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
