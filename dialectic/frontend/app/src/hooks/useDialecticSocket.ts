import { useEffect, useRef, useCallback, useState } from 'react'
import { PARTICIPANT_NAME } from '../lib/productIdentity.ts'
import { useAppStore } from '../stores/appStore.ts'
import { api } from '../lib/api.ts'
import { groupAttachmentsByMessage, isUuid } from '../lib/attachments.ts'
import type {
  Message,
  ProtocolState,
  Commitment,
  TradingSnapshot,
  Thread,
  Memory,
  PresenceUser,
  Reaction,
  LLMToolActivity,
  MessageMetadata,
  MessageAnchor,
  MessageRef,
  Attachment,
} from '../types/index.ts'

const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_RECONNECT_DELAY = 1000;
const MAX_RECONNECT_DELAY = 30000;
const HEARTBEAT_INTERVAL = 30000;

interface ServerMessage {
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export function useDialecticSocket(options?: {
  /**
   * Fired when THIS user's fork lands. Selection is the navigation hook's
   * job — the socket hydrates the thread record and hands the destination
   * up; it never sets a destination itself.
   */
  onOwnFork?: (thread: Thread) => void
}) {
  // Ref-held so an unstable callback identity can never churn the socket.
  const optionsRef = useRef(options)
  useEffect(() => {
    optionsRef.current = options
  }, [options])
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const connectRef = useRef<() => void>(() => {});
  const [isConnected, setIsConnected] = useState(false);

  const user = useAppStore((s) => s.user);
  const accessToken = useAppStore((s) => s.accessToken);
  const currentRoom = useAppStore((s) => s.currentRoom);
  const roomToken = useAppStore((s) => s.roomToken);
  const currentThread = useAppStore((s) => s.currentThread);

  const addMessage = useAppStore((s) => s.addMessage);
  const setTypingUser = useAppStore((s) => s.setTypingUser);
  const setLLMState = useAppStore((s) => s.setLLMState);
  const setDeepDiveActive = useAppStore((s) => s.setDeepDiveActive);
  const updateStreamingContent = useAppStore((s) => s.updateStreamingContent);
  const appendStreamingToken = useAppStore((s) => s.appendStreamingToken);
  const setThreads = useAppStore((s) => s.setThreads);
  const setMemories = useAppStore((s) => s.setMemories);
  const setOnlineUsers = useAppStore((s) => s.setOnlineUsers);
  const setProtocol = useAppStore((s) => s.setProtocol);
  const updateProtocolPhase = useAppStore((s) => s.updateProtocolPhase);
  const addCommitment = useAppStore((s) => s.addCommitment);
  const setActiveCommitments = useAppStore((s) => s.setActiveCommitments);
  const setSurfacedCommitments = useAppStore((s) => s.setSurfacedCommitments);
  const setTradingConfig = useAppStore((s) => s.setTradingConfig);
  const editMessage = useAppStore((s) => s.editMessage);
  const removeMessage = useAppStore((s) => s.removeMessage);
  const mergeMessageMetadata = useAppStore((s) => s.mergeMessageMetadata);
  const setMessageReactions = useAppStore((s) => s.setMessageReactions);
  const setAllReactions = useAppStore((s) => s.setAllReactions);
  const recordToolActivity = useAppStore((s) => s.recordToolActivity);
  const clearToolActivity = useAppStore((s) => s.clearToolActivity);
  const setMessageAttachments = useAppStore((s) => s.setMessageAttachments);
  const setAllAttachments = useAppStore((s) => s.setAllAttachments);

  const send = useCallback((type: string, payload: Record<string, unknown>): boolean => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return false;
    wsRef.current.send(JSON.stringify({ type, payload }));
    return true;
  }, []);

  // Deep components (proposal cards) act through the live socket without
  // prop-drilling — the store carries the sender while this hook is mounted.
  const setWsSend = useAppStore((s) => s.setWsSend);
  useEffect(() => {
    setWsSend(send);
    return () => setWsSend(null);
  }, [send, setWsSend]);

  const refreshThreads = useCallback(async () => {
    const state = useAppStore.getState();
    if (!state.currentRoom || !state.roomToken) return;
    api.setToken(state.roomToken);
    try {
      const threads = await api.getThreads(state.currentRoom.id) as Thread[];
      setThreads(threads);
    } catch (error) {
      console.error('[WS] Failed to refresh threads:', error);
    }
  }, [setThreads]);

  const refreshMemories = useCallback(async () => {
    const state = useAppStore.getState();
    if (!state.currentRoom || !state.roomToken) return;
    api.setToken(state.roomToken);
    try {
      const memories = await api.getMemories(state.currentRoom.id) as Memory[];
      setMemories(memories);
    } catch (error) {
      console.error('[WS] Failed to refresh memories:', error);
    }
  }, [setMemories]);

  const refreshPresence = useCallback(async () => {
    const state = useAppStore.getState();
    if (!state.currentRoom || !state.roomToken) return;
    api.setToken(state.roomToken);
    try {
      const users = await api.getPresence(state.currentRoom.id) as PresenceUser[];
      setOnlineUsers(users);
    } catch (error) {
      console.error('[WS] Failed to refresh presence:', error);
    }
  }, [setOnlineUsers]);

  const refreshCommitments = useCallback(async () => {
    const state = useAppStore.getState();
    if (!state.currentRoom || !state.roomToken) return;
    api.setToken(state.roomToken);
    try {
      const commitments = await api.getCommitments(state.currentRoom.id) as Commitment[];
      setActiveCommitments(commitments);
    } catch (error) {
      console.error('[WS] Failed to refresh commitments:', error);
    }
  }, [setActiveCommitments]);

  /**
   * Fill in the media carried by a set of messages.
   *
   * Non-UUID ids are dropped rather than sent: the endpoint 400s on one bad id
   * and fails the whole batch with it, which would cost every real message in
   * the window its attachments.
   */
  const fetchAttachmentsFor = useCallback(async (
    messageIds: string[], expectedThreadId: string,
  ) => {
    const state = useAppStore.getState();
    if (!state.currentRoom || !state.roomToken) return;
    const roomId = state.currentRoom.id;
    const ids = messageIds.filter(isUuid);
    if (ids.length === 0) return;
    api.setToken(state.roomToken);
    try {
      const records = await api.listAttachments(roomId, ids);
      const active = useAppStore.getState();
      if (
        active.currentRoom?.id !== roomId
        || active.currentThread?.id !== expectedThreadId
      ) return;
      if (records.length > 0) setAllAttachments(groupAttachmentsByMessage(records));
    } catch (error) {
      console.error('[WS] Failed to load attachments:', error);
    }
  }, [setAllAttachments]);

  /** Media for every message currently loaded — called after a history load. */
  const refreshAttachments = useCallback(async (expectedThreadId?: string) => {
    const state = useAppStore.getState();
    const threadId = expectedThreadId ?? state.currentThread?.id;
    if (!threadId) return;
    await fetchAttachmentsFor(
      state.messages.map((message) => message.id), threadId,
    );
  }, [fetchAttachmentsFor]);

  const payloadMatchesActiveThread = useCallback((payload: Record<string, unknown>): boolean => {
    const nestedMessage = payload.message && typeof payload.message === 'object'
      ? payload.message as Record<string, unknown>
      : null;
    const payloadThreadId = typeof payload.thread_id === 'string'
      ? payload.thread_id
      : typeof nestedMessage?.thread_id === 'string'
        ? nestedMessage.thread_id
        : null;
    const activeThreadId = useAppStore.getState().currentThread?.id;
    return Boolean(activeThreadId && payloadThreadId === activeThreadId);
  }, []);

  const handleMessage = useCallback((event: MessageEvent) => {
    let data: ServerMessage;
    try {
      data = JSON.parse(event.data as string) as ServerMessage;
    } catch {
      console.error('Failed to parse WebSocket message');
      return;
    }

    const { type, payload } = data;

    switch (type) {
      case 'message_created':
        if (!payloadMatchesActiveThread(payload)) break;
        addMessage(payload as unknown as Message);
        // The server binds attachments inside the send transaction, so the
        // broadcast is the first read that can carry the media — no echo-bind,
        // no probe.
        if (
          typeof payload.id === 'string' &&
          Array.isArray(payload.attachments) &&
          payload.attachments.length > 0
        ) {
          setMessageAttachments(payload.id, payload.attachments as Attachment[]);
        }
        void refreshThreads();
        if (payload.speaker_type !== 'human') setLLMState(false, false);
        break;

      case 'message_edited':
        if (typeof payload.id === 'string') {
          editMessage(
            payload.id,
            typeof payload.content === 'string' ? payload.content : '',
            typeof payload.edited_at === 'string' ? payload.edited_at : new Date().toISOString(),
          );
        }
        break;

      case 'message_deleted':
        if (typeof payload.id === 'string') removeMessage(payload.id);
        break;

      case 'message_metadata':
        // Server-side enrichment (e.g. detected commitment proposals)
        // landed on an existing message — merge the patch in place.
        if (
          typeof payload.message_id === 'string' &&
          payload.metadata_patch && typeof payload.metadata_patch === 'object'
        ) {
          mergeMessageMetadata(
            payload.message_id,
            payload.metadata_patch as Record<string, unknown>,
          );
        }
        break;

      case 'reaction_updated':
        // The server sends the complete set for the message, not a delta, so a
        // client that missed an event still converges.
        if (typeof payload.message_id === 'string') {
          setMessageReactions(
            payload.message_id,
            Array.isArray(payload.reactions) ? payload.reactions as Reaction[] : [],
          );
        }
        break;

      case 'user_typing':
        setTypingUser(
          payload.user_id as string,
          typeof payload.typing === 'boolean'
            ? payload.typing
            : payload.is_typing === true,
        );
        break;

      case 'presence_update':
      case 'user_joined':
      case 'user_left':
        void refreshPresence();
        break;

      case 'llm_thinking':
        if (!payloadMatchesActiveThread(payload)) break;
        setLLMState(true, false);
        break;

      case 'llm_streaming':
        if (!payloadMatchesActiveThread(payload)) break;
        // Server contract: one token per event ({token, index}), matching
        // the mobile client. The previous code read payload.content, which
        // the server never sends — streamed text silently never rendered.
        if (typeof payload.token === 'string') {
          appendStreamingToken(payload.token);
        } else if (typeof payload.content === 'string') {
          updateStreamingContent(payload.content);
        }
        setLLMState(true, true);
        break;

      case 'llm_tool_activity': {
        if (!payloadMatchesActiveThread(payload)) break;
        if (typeof payload.thread_id === 'string' && typeof payload.tool === 'string') {
          recordToolActivity(payload.thread_id, {
            tool: payload.tool,
            label: typeof payload.label === 'string' ? payload.label : 'checking',
            status: (payload.status as LLMToolActivity['status']) ?? 'started',
            latency_ms: typeof payload.latency_ms === 'number' ? payload.latency_ms : undefined,
          });
        }
        break;
      }

      case 'llm_done': {
        if (!payloadMatchesActiveThread(payload)) break;
        // There is no payload.message. Build the persisted message from the
        // authoritative fields carried by llm_done.
        setLLMState(false, false);
        if (typeof payload.thread_id === 'string') clearToolActivity(payload.thread_id);
        if (payload.message) {
          addMessage(payload.message as unknown as Message);
        } else if (typeof payload.message_id === 'string') {
          addMessage({
            id: payload.message_id,
            thread_id: (payload.thread_id as string) ?? '',
            sequence: typeof payload.sequence === 'number'
              ? payload.sequence
              : Number.MAX_SAFE_INTEGER,
            created_at: typeof payload.created_at === 'string'
              ? payload.created_at
              : new Date().toISOString(),
            speaker_type: typeof payload.speaker_type === 'string'
              ? payload.speaker_type as Message['speaker_type']
              : 'llm_primary',
            user_id: null,
            message_type: typeof payload.message_type === 'string'
              ? payload.message_type as Message['message_type']
              : 'text',
            content: (payload.content as string) ?? '',
            user_name: payload.speaker_type === 'llm_provoker' ? 'Provoker' : PARTICIPANT_NAME,
            // Only path the tool trace takes to the client — the REST message
            // list projects a fixed field set with no metadata in it.
            metadata: (payload.metadata as MessageMetadata | undefined) ?? null,
          } as Message);
          // A document the turn wrote (write_document) rides llm_done the way
          // a human upload rides message_created — bound server-side already.
          if (Array.isArray(payload.attachments) && payload.attachments.length > 0) {
            setMessageAttachments(payload.message_id, payload.attachments as Attachment[]);
          }
        }
        void refreshThreads();
        break;
      }

      case 'llm_error':
        if (!payloadMatchesActiveThread(payload)) break;
        setLLMState(false, false);
        if (typeof payload.thread_id === 'string') clearToolActivity(payload.thread_id);
        console.error('[LLM] stream error:', payload.error);
        break;

      case 'llm_cancelled':
        if (!payloadMatchesActiveThread(payload)) break;
        setLLMState(false, false);
        if (typeof payload.thread_id === 'string') clearToolActivity(payload.thread_id);
        break;

      // Research-mode brackets: the dive between them speaks the ordinary
      // llm_* vocabulary above, so all these two do is keep the composer's
      // Research button disarmed while one is in flight.
      case 'deep_dive_started':
        setDeepDiveActive(true);
        break;

      case 'deep_dive_done':
        setDeepDiveActive(false);
        break;

      case 'annotation_created':
        if (!payloadMatchesActiveThread(payload)) break;
        addMessage(payload as unknown as Message);
        void refreshThreads();
        break;

      case 'protocol_started':
        if (!payloadMatchesActiveThread(payload)) break;
        setProtocol({
          id: payload.protocol_id as string,
          thread_id: payload.thread_id as string,
          protocol_type: payload.protocol_type as ProtocolState['protocol_type'],
          status: 'active',
          current_phase: (payload.current_phase as number) ?? 0,
          total_phases: payload.total_phases as number,
        });
        break;

      case 'protocol_phase_advanced':
        if (!payloadMatchesActiveThread(payload)) break;
        updateProtocolPhase(payload.current_phase as number);
        break;

      case 'protocol_concluded':
      case 'protocol_aborted':
        if (!payloadMatchesActiveThread(payload)) break;
        setProtocol(null);
        break;

      // Authoritative snapshot sent after auth and every switch_thread:
      // replace, never merge, so a cold client sees what the server holds.
      case 'protocol_state':
        if (!payloadMatchesActiveThread(payload)) break;
        setProtocol((payload.protocol as ProtocolState | null) ?? null);
        break;

      case 'commitment_created':
        addCommitment(payload as unknown as Commitment);
        break;

      case 'commitment_resolved':
      case 'commitment_confidence_updated':
        void refreshCommitments();
        break;

      case 'commitment_surfaced':
        setSurfacedCommitments(
          (payload.commitments ?? [payload]) as unknown as Commitment[],
        );
        break;

      case 'thread_created':
      case 'thread_forked': {
        void refreshThreads();
        // The collaborator who created a branch should land in it immediately;
        // everyone else keeps reading their current branch.
        if (
          payload.created_by_user_id === useAppStore.getState().user?.id &&
          typeof payload.id === 'string' &&
          typeof payload.room_id === 'string'
        ) {
          const forked: Thread = {
            id: payload.id,
            room_id: payload.room_id,
            parent_thread_id: typeof payload.parent_thread_id === 'string'
              ? payload.parent_thread_id
              : null,
            title: typeof payload.title === 'string' ? payload.title : null,
            message_count: typeof payload.message_count === 'number' ? payload.message_count : 0,
          };
          // Hydrate the record so navigation can validate the destination
          // before refreshThreads resolves; never select it here.
          const state = useAppStore.getState();
          if (!state.threads.some((thread) => thread.id === forked.id)) {
            state.setThreads([...state.threads, forked]);
          }
          optionsRef.current?.onOwnFork?.(forked);
        }
        break;
      }

      case 'memory_updated':
        void refreshMemories();
        break;

      case 'trading_update':
        // Trading snapshot pushed from tradingDesk bridge
        if (payload && payload.v) {
          setTradingConfig(payload as unknown as TradingSnapshot);
        }
        break;

      case 'error':
        console.error('[WS] Server error:', payload.error ?? payload.message ?? payload);
        break;

      case 'pong':
        // Heartbeat acknowledged
        break;

      default:
        // Unknown message types logged for debugging
        if (import.meta.env.DEV) {
          console.log('[WS] Unhandled message type:', type, payload);
        }
    }
  }, [
    addMessage,
    setTypingUser,
    setLLMState,
    updateStreamingContent,
    appendStreamingToken,
    setProtocol,
    updateProtocolPhase,
    addCommitment,
    refreshCommitments,
    setSurfacedCommitments,
    setTradingConfig,
    payloadMatchesActiveThread,
    refreshThreads,
    refreshMemories,
    refreshPresence,
    editMessage,
    removeMessage,
    mergeMessageMetadata,
    setMessageReactions,
    recordToolActivity,
    clearToolActivity,
    setMessageAttachments,
    setDeepDiveActive,
  ]);

  const connect = useCallback(() => {
    if (!currentRoom || !roomToken || !user) return;

    // Clean up existing connection + heartbeat to prevent leaks on rapid reconnect
    clearInterval(heartbeatTimerRef.current);
    if (wsRef.current) {
      const existing = wsRef.current;
      wsRef.current = null;
      existing.onclose = null;
      existing.close();
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${currentRoom.id}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      // Send auth handshake as first message
      ws.send(JSON.stringify({
        token: roomToken,
        access_token: accessToken,
        user_id: user.id,
        thread_id: useAppStore.getState().currentThread?.id ?? null,
      }));

      setIsConnected(true);
      reconnectAttemptRef.current = 0;

      // Start heartbeat
      heartbeatTimerRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: 'presence_heartbeat',
            payload: {},
          }));
        }
      }, HEARTBEAT_INTERVAL);
    };

    ws.onmessage = handleMessage;

    ws.onclose = (event) => {
      if (wsRef.current !== ws) return;
      setIsConnected(false);
      clearInterval(heartbeatTimerRef.current);

      // Don't reconnect on intentional close (4001 = auth failure, 4002 = not member)
      if (event.code === 4001 || event.code === 4002) {
        console.error('[WS] Auth failed:', event.reason);
        return;
      }

      // Exponential backoff reconnect
      if (reconnectAttemptRef.current < MAX_RECONNECT_ATTEMPTS) {
        const delay = Math.min(
          BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttemptRef.current),
          MAX_RECONNECT_DELAY,
        );
        reconnectAttemptRef.current++;

        if (import.meta.env.DEV) {
          console.log(`[WS] Reconnecting in ${delay}ms (attempt ${reconnectAttemptRef.current}/${MAX_RECONNECT_ATTEMPTS})`);
        }

        reconnectTimerRef.current = setTimeout(() => connectRef.current(), delay);
      } else {
        console.error('[WS] Max reconnection attempts reached');
      }
    };

    ws.onerror = () => {
      // onerror is always followed by onclose, so just log
      console.error('[WS] Connection error');
    };
  }, [currentRoom, roomToken, accessToken, user, handleMessage]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  // Connect/disconnect on room change
  useEffect(() => {
    if (currentRoom && roomToken && user) {
      reconnectAttemptRef.current = 0;
      connect();
    }

    return () => {
      clearTimeout(reconnectTimerRef.current);
      clearInterval(heartbeatTimerRef.current);
      reconnectAttemptRef.current = MAX_RECONNECT_ATTEMPTS; // Prevent reconnect on unmount
      if (wsRef.current) {
        const ws = wsRef.current;
        wsRef.current = null;
        ws.onclose = null;
        ws.close();
      }
    };
  }, [currentRoom?.id, roomToken, user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Wake the socket when the device comes back.
  //
  // WHY: the backoff ladder above gives up after MAX_RECONNECT_ATTEMPTS and
  // then only console.errors. On a desktop that ceiling is nearly unreachable;
  // on a phone it is the NORMAL path. Lock the screen and iOS suspends the
  // page — the socket dies, and the ten attempts burn through their capped
  // backoff (~1s..30s, well under a minute of wall clock) while nobody is
  // looking. Unlock, and the room is permanently "Offline" with no control to
  // press: the header's connection label is a `<span>`, and the only cure is a
  // full reload. The installed PWA is the product's reach strategy, so this is
  // the platform it fails on.
  //
  // Resetting the counter is what makes the retry possible — the ladder is not
  // broken, it is exhausted, and a return to the foreground is exactly the new
  // information that says the exhausted verdict is stale.
  //
  // Safe against the unmount sentinel on line 581: this listener is registered
  // in an effect whose cleanup removes it, so an unmounted hook cannot be
  // revived by a later visibility change. Guarded on an already-open socket so
  // an ordinary tab switch is free.
  useEffect(() => {
    if (!currentRoom || !roomToken || !user) return;

    const revive = () => {
      if (document.visibilityState !== 'visible') return;
      if (wsRef.current?.readyState === WebSocket.OPEN) return;
      clearTimeout(reconnectTimerRef.current);
      reconnectAttemptRef.current = 0;
      connectRef.current();
    };

    document.addEventListener('visibilitychange', revive);
    window.addEventListener('online', revive);
    window.addEventListener('focus', revive);
    return () => {
      document.removeEventListener('visibilitychange', revive);
      window.removeEventListener('online', revive);
      window.removeEventListener('focus', revive);
    };
  }, [currentRoom?.id, roomToken, user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the server-side connection context aligned with the selected branch
  // without reconnecting the room socket.
  useEffect(() => {
    if (!currentThread?.id) return;
    setLLMState(false, false);
    send('switch_thread', { thread_id: currentThread.id });
  }, [currentThread?.id, send, setLLMState]);

  // --- Outbound helpers ---

  const sendMessage = useCallback(
    (
      content: string,
      messageType?: string,
      referencesMessageId?: string | null,
      attachmentIds?: string[],
      tags?: string[],
      // The working surface's slots: what the message is ABOUT (a node or
      // edge of the causal graph) and what it ATTACHES (an update dropped
      // onto that node). Validated by proposal_intake at the door.
      extra?: { anchor?: MessageAnchor | null; refs?: MessageRef[] },
    ): boolean => (
      send('send_message', {
        content,
        type: messageType ?? 'text',
        thread_id: useAppStore.getState().currentThread?.id,
        // Omitted rather than sent as null: the handler validates this field as a
        // UUID whenever it is present.
        ...(referencesMessageId ? { references_message_id: referencesMessageId } : {}),
        // Omitted when empty for the same reason — and because the server binds
        // them in the message transaction, they never travel separately.
        ...(attachmentIds && attachmentIds.length > 0 ? { attachment_ids: attachmentIds } : {}),
        // Omitted when empty, again for the same reason: the server validates
        // tags against a fixed vocabulary whenever the key is present, and an
        // empty list is an error there rather than "no tags".
        ...(tags && tags.length > 0 ? { tags } : {}),
        ...(extra?.anchor ? { anchor: extra.anchor } : {}),
        ...(extra?.refs && extra.refs.length > 0 ? { refs: extra.refs } : {}),
      })
    ),
    [send],
  );

  // WHY: the server has recorded read receipts since the schema was written and
  // derives every unread badge from them, but no client ever sent one — so
  // message_receipts was empty and unread counts only ever grew.
  const markMessageRead = useCallback(
    (messageId: string): boolean => send('message_read', { message_id: messageId }),
    [send],
  );

  const editMessageContent = useCallback(
    (messageId: string, content: string): boolean =>
      send('edit_message', { message_id: messageId, content }),
    [send],
  );

  const deleteMessage = useCallback(
    (messageId: string): boolean => send('delete_message', { message_id: messageId }),
    [send],
  );

  const toggleReaction = useCallback(
    (messageId: string, emoji: string, isOn: boolean): boolean =>
      send(isOn ? 'remove_reaction' : 'add_reaction', { message_id: messageId, emoji }),
    [send],
  );

  const refreshReactions = useCallback(async (expectedThreadId?: string) => {
    const state = useAppStore.getState();
    if (!state.currentThread || !state.roomToken) return;
    const threadId = expectedThreadId ?? state.currentThread.id;
    api.setToken(state.roomToken);
    try {
      const rows = await api.getThreadReactions(threadId) as
        { message_id: string; emoji: string; user_ids: string[]; user_names: string[] }[];
      if (useAppStore.getState().currentThread?.id !== threadId) return;
      const grouped: Record<string, Reaction[]> = {};
      for (const row of rows) {
        (grouped[row.message_id] ??= []).push({
          emoji: row.emoji, user_ids: row.user_ids, user_names: row.user_names,
        });
      }
      setAllReactions(grouped);
    } catch (error) {
      console.error('[WS] Failed to refresh reactions:', error);
    }
  }, [setAllReactions]);

  const sendTypingStart = useCallback((): boolean => (
    send('typing_start', {
      typing: true,
      thread_id: useAppStore.getState().currentThread?.id,
    })
  ), [send]);

  const sendTypingStop = useCallback((): boolean => (
    send('typing_stop', {
      typing: false,
      thread_id: useAppStore.getState().currentThread?.id,
    })
  ), [send]);

  const sendTypingContent = useCallback(
    (content: string): boolean => (
      send('typing_content', {
        content,
        thread_id: useAppStore.getState().currentThread?.id,
      })
    ),
    [send],
  );

  const switchThread = useCallback(
    (threadId: string): boolean => send('switch_thread', { thread_id: threadId }),
    [send],
  );

  const invokeProtocol = useCallback(
    (protocolType: string, config: Record<string, unknown>): boolean =>
      send('invoke_protocol', {
        protocol_type: protocolType,
        config,
        thread_id: useAppStore.getState().currentThread?.id,
      }),
    [send],
  );

  const advanceProtocol = useCallback(
    (protocolId: string) => {
      send('advance_protocol', { protocol_id: protocolId });
    },
    [send],
  );

  const abortProtocol = useCallback(
    (protocolId: string) => {
      send('abort_protocol', { protocol_id: protocolId });
    },
    [send],
  );

  const summonLLM = useCallback(() => {
    send('summon_llm', {
      thread_id: useAppStore.getState().currentThread?.id,
    });
  }, [send]);

  const cancelLLM = useCallback(() => {
    send('cancel_llm', {
      thread_id: useAppStore.getState().currentThread?.id,
    });
  }, [send]);

  // Research mode: the composer's text IS the question; the server runs the
  // long tool loop and the brief lands as an llm_primary message.
  const sendDeepDive = useCallback(
    (question: string): boolean => (
      send('deep_dive', {
        question,
        thread_id: useAppStore.getState().currentThread?.id,
      })
    ),
    [send],
  );

  const forkThread = useCallback(
    (sourceThreadId: string, forkMessageId: string, title?: string): boolean => (
      send('fork_thread', {
        source_thread_id: sourceThreadId,
        fork_after_message_id: forkMessageId,
        title,
      })
    ),
    [send],
  );

  const createCommitment = useCallback(
    (
      claim: string,
      criteria: string,
      category?: string,
      deadline?: string,
      initialConfidence?: number,
    ): boolean => {
      return send('create_commitment', {
        claim,
        resolution_criteria: criteria,
        category: category ?? 'commitment',
        deadline,
        initial_confidence: initialConfidence,
        thread_id: useAppStore.getState().currentThread?.id,
      });
    },
    [send],
  );

  const recordConfidence = useCallback(
    (commitmentId: string, confidence: number, reasoning?: string): boolean => {
      return send('record_confidence', {
        commitment_id: commitmentId,
        confidence,
        reasoning,
      });
    },
    [send],
  );

  const resolveCommitment = useCallback(
    (commitmentId: string, resolution: string, resolutionNotes?: string): boolean => (
      send('resolve_commitment', {
        commitment_id: commitmentId,
        resolution,
        resolution_notes: resolutionNotes,
      })
    ),
    [send],
  );

  return {
    isConnected,
    send,
    sendMessage,
    markMessageRead,
    editMessageContent,
    deleteMessage,
    toggleReaction,
    refreshReactions,
    sendTypingStart,
    sendTypingStop,
    sendTypingContent,
    switchThread,
    invokeProtocol,
    advanceProtocol,
    abortProtocol,
    summonLLM,
    cancelLLM,
    sendDeepDive,
    forkThread,
    createCommitment,
    recordConfidence,
    resolveCommitment,
    refreshThreads,
    refreshMemories,
    refreshPresence,
    refreshCommitments,
    refreshAttachments,
  };
}
