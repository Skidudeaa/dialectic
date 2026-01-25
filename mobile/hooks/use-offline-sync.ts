/**
 * ARCHITECTURE: Coordinates offline queue flush and gap sync.
 * WHY: On reconnect, sync missed messages then flush queued outgoing.
 * TRADEOFF: Gap sync first (might receive our own queued messages back).
 */

import { useEffect, useCallback, useRef } from 'react';
import { useWebSocketStore } from '@/stores/websocket-store';
import { offlineQueue } from '@/services/sync/offline-queue';
import { syncMissedMessages } from '@/services/sync/gap-sync';
import { websocketService } from '@/services/websocket';

interface UseOfflineSyncOptions {
  roomId: string;
  token: string;
  onSyncedEvent?: (event: unknown) => void;
  onQueuedMessageSent?: (clientId: string, serverId: string) => void;
}

export function useOfflineSync(options: UseOfflineSyncOptions) {
  const { isConnected, lastSequence, setLastSequence } = useWebSocketStore();
  const wasConnected = useRef(isConnected);
  const isSyncing = useRef(false);

  // Flush offline queue
  const flushQueue = useCallback(async () => {
    const pending = offlineQueue.getPending();

    for (const msg of pending) {
      offlineQueue.markSending(msg.id);
      try {
        websocketService.send({
          type: msg.type,
          payload: {
            ...msg.payload,
            client_id: msg.id, // Include client ID for correlation
          },
        });
        // Note: Actual removal happens when we receive server confirmation
        // For now, mark as sent optimistically
        offlineQueue.markSent(msg.id);
        options.onQueuedMessageSent?.(msg.id, msg.id);
      } catch (e) {
        offlineQueue.markFailed(msg.id);
      }
    }
  }, [options]);

  // Handle reconnection
  useEffect(() => {
    const justConnected = !wasConnected.current && isConnected;
    wasConnected.current = isConnected;

    if (justConnected && !isSyncing.current) {
      isSyncing.current = true;

      // Step 1: Sync missed messages
      syncMissedMessages(
        options.roomId,
        options.token,
        lastSequence,
        (event) => {
          options.onSyncedEvent?.(event);
        }
      )
        .then((newSequence) => {
          setLastSequence(newSequence);
          // Step 2: Flush offline queue
          return flushQueue();
        })
        .finally(() => {
          isSyncing.current = false;
        });
    }
  }, [isConnected, lastSequence, options, flushQueue, setLastSequence]);

  // Enqueue message for offline sending
  const enqueueMessage = useCallback(
    (content: string, threadId: string, messageType: string = 'text') => {
      return offlineQueue.enqueue({
        type: 'send_message',
        payload: {
          content,
          thread_id: threadId,
          message_type: messageType,
        },
      });
    },
    []
  );

  return {
    isConnected,
    pendingCount: offlineQueue.getPending().length,
    enqueueMessage,
    flushQueue,
  };
}
