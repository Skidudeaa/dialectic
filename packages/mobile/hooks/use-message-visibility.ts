/**
 * ARCHITECTURE: Hook to track message visibility for read receipts.
 * WHY: Badge decreases when message scrolls into view (not on room open).
 * TRADEOFF: Visibility detection adds complexity but matches user expectation.
 */

import { useCallback, useRef } from 'react';
import { ViewToken } from 'react-native';
import { useNotificationStore } from '@/stores/notification-store';
import { syncBadgeFromStore } from '@/services/notifications/badge';

interface MessageItem {
  id: string;
  senderId?: string;
  userId?: string;
}

/**
 * Hook to track message visibility for read receipt and badge decrement.
 * CONTEXT.md: Badge decreases when message scrolls into view (not on room open)
 */
export function useMessageVisibility(roomId: string, currentUserId: string) {
  const markMessageSeen = useNotificationStore((state) => state.markMessageSeen);
  const processedIds = useRef(new Set<string>());

  const onViewableItemsChanged = useCallback(
    ({ viewableItems }: { viewableItems: ViewToken[] }) => {
      for (const item of viewableItems) {
        if (!item.isViewable || !item.item) continue;

        const message = item.item as MessageItem;
        const messageId = message.id;

        // Skip if already processed this session
        if (processedIds.current.has(messageId)) continue;

        // Skip own messages (check both senderId and userId for compatibility)
        const messageSenderId = message.senderId || message.userId;
        if (messageSenderId === currentUserId) continue;

        // Mark as seen (triggers badge decrement)
        processedIds.current.add(messageId);
        markMessageSeen(messageId, roomId);
      }

      // Sync badge after processing
      syncBadgeFromStore();
    },
    [roomId, currentUserId, markMessageSeen]
  );

  // Configuration for FlashList/FlatList onViewableItemsChanged
  const viewabilityConfig = useRef({
    itemVisiblePercentThreshold: 50, // 50% visible counts as "seen"
    minimumViewTime: 500, // Must be visible for 500ms
  }).current;

  return {
    onViewableItemsChanged,
    viewabilityConfig,
  };
}
