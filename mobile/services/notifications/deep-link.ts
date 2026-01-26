/**
 * ARCHITECTURE: Deep linking for notification navigation.
 * WHY: Users tap notification expecting to land on relevant conversation.
 * TRADEOFF: 300ms delay on cold start to ensure navigation is ready.
 */

import { router } from 'expo-router';
import * as Notifications from 'expo-notifications';
import type { NotificationData } from './handlers';

/**
 * Navigate to the room and message referenced in notification data.
 * Uses router.replace to avoid adding to navigation stack.
 *
 * Note: scrollToMessage param is passed for future implementation.
 * The room screen can use this to scroll to the specific message.
 *
 * @param data - Notification payload with room_id, thread_id, message_id
 */
export function handleNotificationNavigation(data: NotificationData): void {
  if (!data.room_id || !data.message_id) {
    console.warn('[Notifications] Invalid notification data for navigation');
    return;
  }

  // CONTEXT.md: Navigation replaces current view (not pushed on stack)
  // Note: Room routes will be created in Phase 7. Using type assertion for forward compatibility.
  router.replace({
    pathname: '/(app)/rooms/[roomId]',
    params: {
      roomId: data.room_id,
      threadId: data.thread_id,
      scrollToMessage: data.message_id,
    },
  } as unknown as Parameters<typeof router.replace>[0]);
}

/**
 * Handle notification that launched the app (cold start scenario).
 * Checks for pending notification response and navigates if found.
 *
 * @returns Promise resolving to true if navigation was triggered
 */
export async function handleInitialNotification(): Promise<boolean> {
  // Check for notification that launched the app (cold start)
  const response = await Notifications.getLastNotificationResponseAsync();

  if (response) {
    const data = response.notification.request.content
      .data as unknown as NotificationData;

    if (data.room_id && data.message_id) {
      // Small delay to ensure navigation is ready
      setTimeout(() => {
        handleNotificationNavigation(data);
      }, 300);
      return true;
    }
  }
  return false;
}
