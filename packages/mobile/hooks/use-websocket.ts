/**
 * ARCHITECTURE: React hook that bridges WebSocket service to components.
 * WHY: Hooks provide React-native API for imperative WebSocket operations.
 * TRADEOFF: useEffect deps array requires careful management of options object.
 */

import { useEffect, useCallback, useRef } from 'react';
import { websocketService } from '@/services/websocket';
import { useWebSocketStore } from '@/stores/websocket-store';
import { useNetwork } from './use-network';
import type { InboundMessage, OutboundMessage } from '@/services/websocket/types';

interface UseWebSocketOptions {
  baseUrl: string;
  roomId: string;
  userId: string;
  token: string;
  threadId?: string;
  onMessage?: (message: InboundMessage) => void;
  /** If false, connection won't be established (useful for conditional connection) */
  enabled?: boolean;
}

export function useWebSocket(options: UseWebSocketOptions) {
  const { setConnected, setLastSequence, isConnected } = useWebSocketStore();
  const { isConnected: networkConnected } = useNetwork();

  // Use ref for onMessage to avoid reconnecting on callback changes
  const onMessageRef = useRef(options.onMessage);
  onMessageRef.current = options.onMessage;

  const enabled = options.enabled ?? true;

  useEffect(() => {
    if (!enabled || !options.roomId || !options.userId || !options.token) {
      return;
    }

    websocketService.connect({
      baseUrl: options.baseUrl,
      roomId: options.roomId,
      userId: options.userId,
      token: options.token,
      threadId: options.threadId,
      onConnectionChange: (connected) => {
        setConnected(connected);
      },
      onMessage: (message) => {
        if (message.sequence !== undefined) {
          setLastSequence(message.sequence);
        }
        onMessageRef.current?.(message);
      },
    });

    return () => {
      websocketService.disconnect();
    };
  }, [
    enabled,
    options.baseUrl,
    options.roomId,
    options.userId,
    options.token,
    options.threadId,
    setConnected,
    setLastSequence,
  ]);

  const send = useCallback((message: OutboundMessage) => {
    websocketService.send(message);
  }, []);

  const sendPresenceUpdate = useCallback(
    (status: 'online' | 'away' | 'offline') => {
      websocketService.sendPresenceUpdate(status);
    },
    []
  );

  return {
    /** Whether WebSocket is currently connected */
    isConnected,
    /** Whether device has network connectivity */
    networkConnected,
    /** Send a message through the WebSocket */
    send,
    /** Send a presence status update */
    sendPresenceUpdate,
  };
}
