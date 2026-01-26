/**
 * ARCHITECTURE: Badge service for app icon updates.
 * WHY: Centralized badge management with store sync.
 * TRADEOFF: Async badge updates may lag slightly behind state.
 */

import * as Notifications from 'expo-notifications';
import { useNotificationStore } from '@/stores/notification-store';

/**
 * Update app icon badge to match unread rooms count.
 * CONTEXT.md: Badge count = number of rooms with unread messages
 */
export async function updateBadge(count: number): Promise<void> {
  try {
    await Notifications.setBadgeCountAsync(count);
  } catch (error) {
    console.warn('[Badge] Failed to update badge:', error);
  }
}

/**
 * Clear app icon badge (set to 0).
 */
export async function clearBadge(): Promise<void> {
  await updateBadge(0);
}

/**
 * Sync badge from store state.
 * Call this when app foregrounds or after server sync.
 */
export async function syncBadgeFromStore(): Promise<void> {
  const count = useNotificationStore.getState().totalUnreadRooms;
  await updateBadge(count);
}

/**
 * Fetch badge counts from server and sync to store + badge.
 * Call this on app foreground for multi-device sync.
 *
 * Note: Backend needs GET /notifications/badge endpoint to return:
 * { total_unread_rooms: number, room_counts: Record<string, number> }
 */
export async function fetchAndSyncBadge(api: {
  get: (url: string) => Promise<{ data: { total_unread_rooms: number; room_counts: Record<string, number> } }>;
}): Promise<void> {
  try {
    // Fetch total unread rooms
    const response = await api.get('/notifications/badge');
    const { total_unread_rooms, room_counts } = response.data;

    // Update store
    useNotificationStore.getState().syncFromServer(total_unread_rooms, room_counts);

    // Update badge
    await updateBadge(total_unread_rooms);
  } catch (error) {
    console.warn('[Badge] Failed to fetch badge from server:', error);
    // Fall back to local store
    await syncBadgeFromStore();
  }
}
