import { useEffect, useRef, useCallback, useState } from 'react'
import { useAppStore } from '../stores/appStore.ts'
import type { Message, ProtocolState, Commitment, TradingSnapshot } from '../types/index.ts'

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
  const [isConnected, setIsConnected] = useState(false);

  const user = useAppStore((s) => s.user);
  const currentRoom = useAppStore((s) => s.currentRoom);
  const roomToken = useAppStore((s) => s.roomToken);
  const currentThread = useAppStore((s) => s.currentThread);

  const addMessage = useAppStore((s) => s.addMessage);
  const setTypingUser = useAppStore((s) => s.setTypingUser);
  const setLLMState = useAppStore((s) => s.setLLMState);
  const updateStreamingContent = useAppStore((s) => s.updateStreamingContent);
  const setProtocol = useAppStore((s) => s.setProtocol);
  const updateProtocolPhase = useAppStore((s) => s.updateProtocolPhase);
  const addCommitment = useAppStore((s) => s.addCommitment);
  const setSurfacedCommitments = useAppStore((s) => s.setSurfacedCommitments);
  const setTradingConfig = useAppStore((s) => s.setTradingConfig);

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
        addMessage(payload as unknown as Message);
        break;

      case 'user_typing':
        setTypingUser(
          payload.user_id as string,
          (payload.is_typing as boolean) ?? true,
        );
        break;

      case 'llm_thinking':
        setLLMState(true, false);
        break;

      case 'llm_streaming':
        updateStreamingContent(payload.content as string);
        setLLMState(true, true);
        break;

      case 'llm_done':
        setLLMState(false, false);
        if (payload.message) {
          addMessage(payload.message as unknown as Message);
        }
        break;

      case 'annotation_created':
        addMessage(payload as unknown as Message);
        break;

      case 'protocol_started':
        setProtocol(payload as unknown as ProtocolState);
        break;

      case 'protocol_phase_advanced':
        updateProtocolPhase(payload.current_phase as number);
        break;

      case 'protocol_concluded':
      case 'protocol_aborted':
        setProtocol(null);
        break;

      case 'commitment_created':
        addCommitment(payload as unknown as Commitment);
        break;

      case 'commitment_surfaced':
        setSurfacedCommitments(
          (payload.commitments ?? [payload]) as unknown as Commitment[],
        );
        break;

      case 'thread_forked': {
        // Thread fork events are informational; parent fetches thread list
        break;
      }

      case 'memory_updated':
        // Memory updates handled by periodic refresh or explicit fetch
        break;

      case 'trading_update':
        // Trading snapshot pushed from tradingDesk bridge
        if (payload && payload.v) {
          setTradingConfig(payload as unknown as TradingSnapshot);
        }
        break;

      case 'error':
        console.error('[WS] Server error:', payload.message ?? payload);
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
  }, [addMessage, setTypingUser, setLLMState, updateStreamingContent, setProtocol, updateProtocolPhase, addCommitment, setSurfacedCommitments, setTradingConfig]);

  const connect = useCallback(() => {
    if (!currentRoom || !roomToken || !user) return;

    // Clean up existing connection + heartbeat to prevent leaks on rapid reconnect
    clearInterval(heartbeatTimerRef.current);
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${currentRoom.id}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      // Send auth handshake as first message
      ws.send(JSON.stringify({
        token: roomToken,
        user_id: user.id,
        thread_id: currentThread?.id ?? null,
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

        reconnectTimerRef.current = setTimeout(connect, delay);
      } else {
        console.error('[WS] Max reconnection attempts reached');
      }
    };

    ws.onerror = () => {
      // onerror is always followed by onclose, so just log
      console.error('[WS] Connection error');
    };
  }, [currentRoom, roomToken, user, currentThread?.id, handleMessage]);

  // Connect/disconnect on room change
  useEffect(() => {
    if (currentRoom && roomToken && user) {
      connect();
    }

    return () => {
      clearTimeout(reconnectTimerRef.current);
      clearInterval(heartbeatTimerRef.current);
      reconnectAttemptRef.current = MAX_RECONNECT_ATTEMPTS; // Prevent reconnect on unmount
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [currentRoom?.id, roomToken, user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Outbound helpers ---

  const send = useCallback((type: string, payload: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, payload }));
    }
  }, []);

  const sendMessage = useCallback(
    (content: string, messageType?: string) => {
      send('send_message', {
        content,
        message_type: messageType ?? 'text',
        thread_id: useAppStore.getState().currentThread?.id,
      });
    },
    [send],
  );

  const sendTypingStart = useCallback(() => {
    send('typing_start', {
      thread_id: useAppStore.getState().currentThread?.id,
    });
  }, [send]);

  const sendTypingStop = useCallback(() => {
    send('typing_stop', {
      thread_id: useAppStore.getState().currentThread?.id,
    });
  }, [send]);

  const sendTypingContent = useCallback(
    (content: string) => {
      send('typing_content', {
        content,
        thread_id: useAppStore.getState().currentThread?.id,
      });
    },
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
    (sourceThreadId: string, forkMessageId: string, title?: string) => {
      send('fork_thread', {
        source_thread_id: sourceThreadId,
        fork_message_id: forkMessageId,
        title,
      });
    },
    [send],
  );

  const createCommitment = useCallback(
    (claim: string, criteria: string, category?: string) => {
      send('create_commitment', {
        claim,
        resolution_criteria: criteria,
        category: category ?? 'commitment',
        thread_id: useAppStore.getState().currentThread?.id,
      });
    },
    [send],
  );

  const recordConfidence = useCallback(
    (commitmentId: string, confidence: number, reasoning?: string) => {
      send('record_confidence', {
        commitment_id: commitmentId,
        confidence,
        reasoning,
      });
    },
    [send],
  );

  return {
    isConnected,
    send,
    sendMessage,
    sendTypingStart,
    sendTypingStop,
    sendTypingContent,
    invokeProtocol,
    advanceProtocol,
    abortProtocol,
    summonLLM,
    cancelLLM,
    forkThread,
    createCommitment,
    recordConfidence,
  };
}
