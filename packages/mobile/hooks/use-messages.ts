/**
 * ARCHITECTURE: Hook coordinating messages store, WebSocket, and offline queue.
 * WHY: Single interface for all message operations with automatic offline support.
 * TRADEOFF: Hook complexity vs consistent message handling.
 */

import { useCallback, useMemo } from 'react';
import {
  useMessagesStore,
  Message,
  DeliveryStatus,
} from '@/stores/messages-store';
import { websocketService } from '@/services/websocket';
import { offlineQueue } from '@/services/sync/offline-queue';
import { useWebSocketStore } from '@/stores/websocket-store';
import { v4 as uuidv4 } from 'uuid';

interface UseMessagesOptions {
  threadId: string;
  userId: string;
  userName?: string;
}

export type { Message, DeliveryStatus };

export function useMessages({ threadId, userId, userName }: UseMessagesOptions) {
  const {
    messages,
    threadMessages,
    addOptimistic,
    confirmSent,
    addMessage,
    markDelivered,
    markRead,
    markFailed,
    retryFailed,
    setCurrentUserId,
  } = useMessagesStore();
  const { isConnected } = useWebSocketStore();

  // Set current user on mount
  useMemo(() => {
    setCurrentUserId(userId);
  }, [userId, setCurrentUserId]);

  // Get ordered messages for thread
  const threadMessageList = useMemo(() => {
    const ids = threadMessages[threadId] || [];
    return ids.map((id) => messages[id]).filter(Boolean) as Message[];
  }, [threadMessages, threadId, messages]);

  // Send message (handles online/offline)
  const sendMessage = useCallback(
    (content: string, messageType: string = 'text') => {
      const clientId = uuidv4();
      const now = new Date().toISOString();

      // Add optimistic message to store
      addOptimistic(clientId, {
        threadId,
        content,
        senderId: userId,
        senderName: userName,
        createdAt: now,
      });

      if (isConnected) {
        // Send via WebSocket
        websocketService.send({
          type: 'send_message',
          payload: {
            content,
            thread_id: threadId,
            message_type: messageType,
            client_id: clientId,
          },
        });
      } else {
        // Queue for offline
        offlineQueue.enqueue({
          type: 'send_message',
          payload: {
            content,
            thread_id: threadId,
            message_type: messageType,
          },
        });
      }

      return clientId;
    },
    [threadId, userId, userName, isConnected, addOptimistic]
  );

  // Handle incoming message_created event
  const handleMessageCreated = useCallback(
    (payload: {
      message_id: string;
      client_id?: string;
      content: string;
      user_id: string;
      display_name?: string;
      thread_id: string;
      sequence: number;
      created_at: string;
    }) => {
      // Check if this is confirmation of our optimistic message
      if (payload.client_id && payload.user_id === userId) {
        confirmSent(payload.client_id, payload.message_id, payload.sequence);
      } else {
        // Message from another user
        addMessage({
          id: payload.message_id,
          threadId: payload.thread_id,
          content: payload.content,
          senderId: payload.user_id,
          senderName: payload.display_name,
          createdAt: payload.created_at,
          sequence: payload.sequence,
          deliveryStatus: 'delivered',
          readBy: [],
        });

        // Send delivery receipt
        websocketService.send({
          type: 'message_delivered',
          payload: { message_id: payload.message_id },
        });
      }
    },
    [userId, confirmSent, addMessage]
  );

  // Handle delivery receipt
  const handleDeliveryReceipt = useCallback(
    (payload: { message_id: string; status: string }) => {
      markDelivered(payload.message_id);
    },
    [markDelivered]
  );

  // Handle read receipt
  const handleReadReceipt = useCallback(
    (payload: { message_id: string; reader_id: string }) => {
      markRead(payload.message_id, payload.reader_id);
    },
    [markRead]
  );

  // Mark message as read (call when message becomes visible)
  const markAsRead = useCallback(
    (messageId: string) => {
      const msg = messages[messageId];
      if (!msg || msg.isMine) return; // Don't send read receipt for own messages

      websocketService.send({
        type: 'message_read',
        payload: { message_id: messageId },
      });
    },
    [messages]
  );

  // Retry failed message
  const retryMessage = useCallback(
    (clientId: string) => {
      const msg = messages[clientId];
      if (!msg || msg.deliveryStatus !== 'failed') return;

      retryFailed(clientId);

      if (isConnected) {
        websocketService.send({
          type: 'send_message',
          payload: {
            content: msg.content,
            thread_id: msg.threadId,
            message_type: 'text',
            client_id: clientId,
          },
        });
      }
    },
    [messages, isConnected, retryFailed]
  );

  return {
    messages: threadMessageList,
    sendMessage,
    markAsRead,
    retryMessage,
    handleMessageCreated,
    handleDeliveryReceipt,
    handleReadReceipt,
  };
}
