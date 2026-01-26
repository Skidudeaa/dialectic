/**
 * ARCHITECTURE: Singleton WebSocket service with automatic reconnection.
 * WHY: Single connection per room prevents duplicate messages and simplifies state.
 * TRADEOFF: Singleton pattern limits testability, but matches mobile app lifecycle.
 */

import ReconnectingWebSocket, {
  ErrorEvent as WSErrorEvent,
} from 'reconnecting-websocket';
import { RECONNECT_OPTIONS } from './reconnect';
import type { InboundMessage, OutboundMessage, WebSocketConfig } from './types';

const HEARTBEAT_INTERVAL_MS = 30000; // 30 seconds

// LLM event types for callback dispatch
const LLM_EVENT_TYPES = ['llm_thinking', 'llm_streaming', 'llm_done', 'llm_error'] as const;

class WebSocketService {
  private ws: ReconnectingWebSocket | null = null;
  private config: WebSocketConfig | null = null;
  private lastSequence: number = 0;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private llmEventCallback: ((type: string, payload: Record<string, unknown>) => void) | null = null;

  /**
   * Connect to a room's WebSocket endpoint.
   * Will automatically reconnect on disconnection using exponential backoff.
   */
  connect(config: WebSocketConfig): void {
    // Disconnect any existing connection first
    if (this.ws) {
      this.disconnect();
    }

    this.config = config;
    this.lastSequence = 0;

    // Build WebSocket URL with auth params
    const wsProtocol = config.baseUrl.startsWith('https') ? 'wss' : 'ws';
    const wsBaseUrl = config.baseUrl.replace(/^http/, wsProtocol);
    const wsUrl = new URL(`${wsBaseUrl}/ws/${config.roomId}`);
    wsUrl.searchParams.set('token', config.token);
    wsUrl.searchParams.set('user_id', config.userId);
    if (config.threadId) {
      wsUrl.searchParams.set('thread_id', config.threadId);
    }

    this.ws = new ReconnectingWebSocket(wsUrl.toString(), [], RECONNECT_OPTIONS);

    // Bind event handlers
    this.ws.addEventListener('open', this.handleOpen);
    this.ws.addEventListener('close', this.handleClose);
    this.ws.addEventListener('message', this.handleMessage);
    this.ws.addEventListener('error', this.handleError);
  }

  /**
   * Disconnect and clean up resources.
   */
  disconnect(): void {
    this.stopHeartbeat();

    if (this.ws) {
      this.ws.removeEventListener('open', this.handleOpen);
      this.ws.removeEventListener('close', this.handleClose);
      this.ws.removeEventListener('message', this.handleMessage);
      this.ws.removeEventListener('error', this.handleError);
      this.ws.close();
      this.ws = null;
    }

    this.config = null;
  }

  /**
   * Send a message through the WebSocket.
   * Messages are automatically buffered if disconnected (up to maxEnqueuedMessages).
   */
  send(message: OutboundMessage): void {
    if (!this.ws) {
      console.warn('[WebSocket] Cannot send - not connected');
      return;
    }

    this.ws.send(JSON.stringify(message));
  }

  /**
   * Send a presence status update.
   */
  sendPresenceUpdate(status: 'online' | 'away' | 'offline'): void {
    this.send({
      type: 'presence_update',
      payload: { status },
    });
  }

  /**
   * Get the last received sequence number (for gap sync).
   */
  getLastSequence(): number {
    return this.lastSequence;
  }

  /**
   * Register callback for LLM events (llm_thinking, llm_streaming, llm_done, llm_error).
   */
  onLLMEvent(callback: (type: string, payload: Record<string, unknown>) => void): void {
    this.llmEventCallback = callback;
  }

  /**
   * Unregister LLM event callback.
   */
  offLLMEvent(): void {
    this.llmEventCallback = null;
  }

  // Event handlers bound to preserve `this` context
  private handleOpen = (): void => {
    console.log('[WebSocket] Connected');
    this.config?.onConnectionChange(true);
    this.startHeartbeat();
  };

  private handleClose = (): void => {
    console.log('[WebSocket] Disconnected');
    this.config?.onConnectionChange(false);
    this.stopHeartbeat();
  };

  private handleMessage = (event: MessageEvent): void => {
    try {
      const message: InboundMessage = JSON.parse(event.data);

      // Track sequence for gap detection
      if (message.sequence !== undefined) {
        this.lastSequence = message.sequence;
      }

      // Dispatch LLM events to registered callback
      if (
        LLM_EVENT_TYPES.includes(message.type as (typeof LLM_EVENT_TYPES)[number]) &&
        this.llmEventCallback
      ) {
        this.llmEventCallback(message.type, message.payload);
      }

      this.config?.onMessage(message);
    } catch (error) {
      console.error('[WebSocket] Failed to parse message:', error);
    }
  };

  private handleError = (event: WSErrorEvent): void => {
    console.error('[WebSocket] Error:', event.message || event);
  };

  private startHeartbeat(): void {
    this.stopHeartbeat();

    this.heartbeatInterval = setInterval(() => {
      this.send({
        type: 'presence_heartbeat',
        payload: {},
      });
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }
}

// Singleton instance
export const websocketService = new WebSocketService();

// Re-export types for convenience
export type { InboundMessage, OutboundMessage, WebSocketConfig } from './types';
