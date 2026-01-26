/**
 * ARCHITECTURE: Push token registration with backend.
 * WHY: Backend needs device tokens to send push notifications via Expo Push Service.
 * TRADEOFF: Re-registers on every call; prevents stale tokens (per RESEARCH.md pitfall #3).
 */

import { Platform } from 'react-native';
import { api } from '@/services/api';
import { notificationService } from './index';

/**
 * Register for push notifications and store token with backend.
 * Call on app launch and after user sign-in.
 *
 * @param userId - The current user's ID for server-side token association
 * @returns The Expo push token on success, null on failure
 */
export async function registerForPushNotifications(
  userId: string
): Promise<string | null> {
  // Request permission if not already granted
  const permissionGranted = await notificationService.requestPermission();
  if (!permissionGranted) {
    return null;
  }

  // Get Expo push token
  const token = await notificationService.getExpoPushToken();
  if (!token) {
    return null;
  }

  // Register token with backend
  try {
    await api.post('/notifications/tokens', {
      expo_push_token: token,
      platform: Platform.OS,
      device_name: notificationService.getDeviceName(),
    });

    return token;
  } catch (error) {
    console.error('Failed to register push token with backend:', error);
    return null;
  }
}

/**
 * Unregister a push token from the backend.
 * Call on user sign-out to stop notifications to this device.
 *
 * @param token - The Expo push token to unregister
 */
export async function unregisterPushToken(token: string): Promise<void> {
  try {
    await api.delete('/notifications/tokens', {
      data: { expo_push_token: token },
    });
  } catch (error) {
    // Log but don't throw - unregistration failure is non-critical
    console.error('Failed to unregister push token:', error);
  }
}

/**
 * Refresh the push token registration.
 * Useful for token refresh events or periodic re-registration.
 *
 * @param userId - The current user's ID
 * @returns The (possibly new) Expo push token on success, null on failure
 */
export async function refreshPushToken(userId: string): Promise<string | null> {
  // Simply re-register - backend handles upsert
  return registerForPushNotifications(userId);
}
