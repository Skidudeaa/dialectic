/**
 * ARCHITECTURE: Type definitions for WebSocket message protocol.
 * WHY: Strong typing ensures message format consistency between client and server.
 * TRADEOFF: Some flexibility lost vs any, but compile-time safety is worth it.
 */

// Message types matching backend MessageTypes
export type InboundMessageType =
  | 'message_created'
  | 'user_joined'
  | 'user_left'
  | 'user_typing'
  | 'presence_update'
  | 'delivery_receipt'
  | 'read_receipt'
  | 'thread_created'
  | 'error'
  | 'pong';

export type OutboundMessageType =
  | 'send_message'
  | 'typing_start'
  | 'typing_stop'
  | 'presence_heartbeat'
  | 'presence_update'
  | 'message_delivered'
  | 'message_read'
  | 'ping';

export interface InboundMessage {
  type: InboundMessageType;
  payload: Record<string, unknown>;
  timestamp: string;
  sequence?: number;
}

export interface OutboundMessage {
  type: OutboundMessageType;
  payload: Record<string, unknown>;
}

export interface WebSocketConfig {
  baseUrl: string;
  roomId: string;
  userId: string;
  token: string;
  threadId?: string;
  onMessage: (message: InboundMessage) => void;
  onConnectionChange: (connected: boolean) => void;
}
