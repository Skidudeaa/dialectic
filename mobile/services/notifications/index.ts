/**
 * ARCHITECTURE: NotificationService singleton for push notification management.
 * WHY: Centralized permission handling and token management.
 * TRADEOFF: Singleton couples lifecycle to app; acceptable for device-level service.
 */

import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import Constants from 'expo-constants';
import { Platform } from 'react-native';
import { setupNotificationChannels } from './channels';

export { setupNotificationChannels, createRoomChannel } from './channels';

class NotificationService {
  private initialized = false;

  /**
   * Initialize notification service (channels, handlers).
   * Call once on app startup.
   */
  async initialize(): Promise<void> {
    if (this.initialized) {
      return;
    }

    // Setup Android notification channels
    await setupNotificationChannels();

    this.initialized = true;
  }

  /**
   * Request notification permissions from the user.
   * Per RESEARCH.md Pattern 1: iOS requests alert, badge, sound.
   *
   * @returns true if permission granted, false otherwise
   */
  async requestPermission(): Promise<boolean> {
    // Push notifications require a physical device
    if (!Device.isDevice) {
      console.warn('Push notifications require a physical device');
      return false;
    }

    // Check existing permission status
    const { status: existingStatus } =
      await Notifications.getPermissionsAsync();
    let finalStatus = existingStatus;

    // Request permission if not already granted
    if (existingStatus !== 'granted') {
      const { status } = await Notifications.requestPermissionsAsync({
        ios: {
          allowAlert: true,
          allowBadge: true,
          allowSound: true,
        },
      });
      finalStatus = status;
    }

    if (finalStatus !== 'granted') {
      console.warn('Push notification permission denied');
      return false;
    }

    return true;
  }

  /**
   * Get the Expo push token for this device.
   * Requires projectId from app config (per RESEARCH.md pitfall #2).
   *
   * @returns Expo push token string or null if unavailable
   */
  async getExpoPushToken(): Promise<string | null> {
    // Push notifications require a physical device
    if (!Device.isDevice) {
      console.warn('Push notifications require a physical device');
      return null;
    }

    // Get projectId from app config
    // Check both locations per RESEARCH.md recommendation
    const projectId =
      Constants.expoConfig?.extra?.eas?.projectId ??
      (Constants as { easConfig?: { projectId?: string } }).easConfig
        ?.projectId;

    if (!projectId) {
      console.warn(
        'Missing projectId in app config. Run: npx eas-cli build:configure'
      );
      return null;
    }

    try {
      const tokenData = await Notifications.getExpoPushTokenAsync({
        projectId,
      });
      return tokenData.data;
    } catch (error) {
      console.error('Failed to get Expo push token:', error);
      return null;
    }
  }

  /**
   * Get current notification permission status.
   */
  async getPermissionStatus(): Promise<Notifications.PermissionStatus> {
    const { status } = await Notifications.getPermissionsAsync();
    return status;
  }

  /**
   * Check if running on a device that supports push.
   */
  isDeviceSupported(): boolean {
    return Device.isDevice ?? false;
  }

  /**
   * Get the device platform.
   */
  getPlatform(): 'ios' | 'android' | 'web' | string {
    return Platform.OS;
  }

  /**
   * Get the device name for token registration.
   */
  getDeviceName(): string | null {
    return Device.deviceName ?? null;
  }
}

// Singleton export
export const notificationService = new NotificationService();
