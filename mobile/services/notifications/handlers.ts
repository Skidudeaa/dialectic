/**
 * ARCHITECTURE: Notification handlers with foreground suppression.
 * WHY: Suppress notifications when user is viewing the same room (per CONTEXT.md).
 * TRADEOFF: Callback-based getCurrentRoomId to avoid stale closure references.
 */

import * as Notifications from 'expo-notifications';

/**
 * Data payload included with push notifications from backend.
 */
export interface NotificationData {
  room_id: string;
  thread_id: string;
  message_id: string;
  type: 'new_message';
}

/**
 * Configure how foreground notifications are displayed.
 * Suppresses notification if user is already viewing the same room.
 *
 * @param getCurrentRoomId - Function that returns the currently viewed room ID (or null)
 */
export function setupNotificationHandler(
  getCurrentRoomId: () => string | null
): void {
  Notifications.setNotificationHandler({
    handleNotification: async (notification) => {
      const data = notification.request.content.data as {
        room_id?: string;
        type?: string;
      };
      const currentRoom = getCurrentRoomId();

      // CONTEXT.md: Suppress if user is viewing the same room
      const shouldShow = data.room_id !== currentRoom;

      return {
        shouldShowBanner: shouldShow,
        shouldShowList: shouldShow,
        shouldPlaySound: shouldShow,
        shouldSetBadge: true, // Always update badge count
      };
    },
  });
}

/**
 * Listen for notification taps (when user interacts with notification).
 * Returns subscription that should be removed on cleanup.
 *
 * @param onNotificationTap - Callback invoked when user taps notification
 * @returns Subscription to remove on cleanup
 */
export function setupNotificationResponseListener(
  onNotificationTap: (data: NotificationData) => void
): Notifications.Subscription {
  return Notifications.addNotificationResponseReceivedListener((response) => {
    const data = response.notification.request.content
      .data as unknown as NotificationData;
    onNotificationTap(data);
  });
}
