import { useEffect, useRef, useCallback, useState } from 'react'
import { useAppStore } from '../stores/appStore.ts'
import { api } from '../lib/api.ts'
import type {
  Message,
  ProtocolState,
  Commitment,
  TradingSnapshot,
  Thread,
  Memory,
  PresenceUser,
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

export function useDialecticSocket() {
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
  const updateStreamingContent = useAppStore((s) => s.updateStreamingContent);
  const appendStreamingToken = useAppStore((s) => s.appendStreamingToken);
  const setThreads = useAppStore((s) => s.setThreads);
  const setThread = useAppStore((s) => s.setThread);
  const setMemories = useAppStore((s) => s.setMemories);
  const setOnlineUsers = useAppStore((s) => s.setOnlineUsers);
  const setProtocol = useAppStore((s) => s.setProtocol);
  const updateProtocolPhase = useAppStore((s) => s.updateProtocolPhase);
  const addCommitment = useAppStore((s) => s.addCommitment);
  const setActiveCommitments = useAppStore((s) => s.setActiveCommitments);
  const setSurfacedCommitments = useAppStore((s) => s.setSurfacedCommitments);
  const setTradingConfig = useAppStore((s) => s.setTradingConfig);

  const send = useCallback((type: string, payload: Record<string, unknown>): boolean => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return false;
    wsRef.current.send(JSON.stringify({ type, payload }));
    return true;
  }, []);

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
        void refreshThreads();
        if (payload.speaker_type !== 'human') setLLMState(false, false);
        break;

      case 'persona_response':
        if (!payloadMatchesActiveThread(payload)) break;
        addMessage(payload as unknown as Message);
        void refreshThreads();
        setLLMState(false, false);
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

      case 'llm_done': {
        if (!payloadMatchesActiveThread(payload)) break;
        // There is no payload.message. Build the persisted message from the
        // authoritative fields carried by llm_done.
        setLLMState(false, false);
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
            user_name: payload.speaker_type === 'llm_provoker' ? 'Provoker' : 'Claude',
          } as Message);
        }
        void refreshThreads();
        break;
      }

      case 'llm_error':
        if (!payloadMatchesActiveThread(payload)) break;
        setLLMState(false, false);
        console.error('[LLM] stream error:', payload.error);
        break;

      case 'llm_cancelled':
        if (!payloadMatchesActiveThread(payload)) break;
        setLLMState(false, false);
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
          setThread({
            id: payload.id,
            room_id: payload.room_id,
            parent_thread_id: typeof payload.parent_thread_id === 'string'
              ? payload.parent_thread_id
              : null,
            title: typeof payload.title === 'string' ? payload.title : null,
            message_count: typeof payload.message_count === 'number' ? payload.message_count : 0,
          });
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
    setThread,
    refreshCommitments,
    setSurfacedCommitments,
    setTradingConfig,
    payloadMatchesActiveThread,
    refreshThreads,
    refreshMemories,
    refreshPresence,
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

  // Keep the server-side connection context aligned with the selected branch
  // without reconnecting the room socket.
  useEffect(() => {
    if (!currentThread?.id) return;
    setLLMState(false, false);
    send('switch_thread', { thread_id: currentThread.id });
  }, [currentThread?.id, send, setLLMState]);

  // --- Outbound helpers ---

  const sendMessage = useCallback(
    (content: string, messageType?: string, referencesMessageId?: string | null): boolean => (
      send('send_message', {
        content,
        type: messageType ?? 'text',
        thread_id: useAppStore.getState().currentThread?.id,
        // Omitted rather than sent as null: the handler validates this field as a
        // UUID whenever it is present.
        ...(referencesMessageId ? { references_message_id: referencesMessageId } : {}),
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
    (protocolType: string, config: Record<string, unknown>) => {
      send('invoke_protocol', {
        protocol_type: protocolType,
        config,
        thread_id: useAppStore.getState().currentThread?.id,
      });
    },
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
    sendTypingStart,
    sendTypingStop,
    sendTypingContent,
    switchThread,
    invokeProtocol,
    advanceProtocol,
    abortProtocol,
    summonLLM,
    cancelLLM,
    forkThread,
    createCommitment,
    recordConfidence,
    resolveCommitment,
    refreshThreads,
    refreshMemories,
    refreshPresence,
    refreshCommitments,
  };
}
