/**
 * macOS notification service implementation.
 *
 * ARCHITECTURE: Placeholder with console logging; native module needed for real notifications.
 * WHY: NSUserNotificationCenter requires native bridging not included in react-native-macos.
 * TRADEOFF: Functional interface ready, but notifications only log until native module added.
 *
 * TODO: Create native module for NSUserNotificationCenter/UNUserNotificationCenter
 * or use node-notifier via Electron-style bridge if deeper integration needed.
 */

import type {
  NotificationService,
  NotificationContent,
  NotificationPermission,
  NotificationResponse,
} from '@dialectic/app';

/**
 * macOS notification service using native NSUserNotificationCenter.
 *
 * For full implementation, would need a native module.
 * This is a placeholder that uses console.log fallback.
 */
class MacOSNotificationService implements NotificationService {
  private listeners: Array<(response: NotificationResponse) => void> = [];

  async requestPermissions(): Promise<NotificationPermission> {
    // macOS notifications are enabled by default for apps
    // User can disable in System Preferences > Notifications
    return { granted: true, canAskAgain: false };
  }

  async getPermissions(): Promise<NotificationPermission> {
    return { granted: true, canAskAgain: false };
  }

  async showNotification(content: NotificationContent): Promise<string> {
    const id = `notification-${Date.now()}`;

    // Placeholder: Log notification (native module needed for real notifications)
    // In production, this would call NativeModules.MacOSNotifications
    console.log('[macOS Notification]', {
      id,
      title: content.title,
      body: content.body,
      data: content.data,
      badge: content.badge,
    });

    // Future: await NativeModules.MacOSNotifications?.showNotification(content);

    return id;
  }

  async cancelNotification(id: string): Promise<void> {
    console.log('[macOS Notification] Cancel:', id);
    // Future: NativeModules.MacOSNotifications?.cancelNotification(id);
  }

  async setBadgeCount(count: number): Promise<void> {
    // Dock badge - requires native module to set NSDockTile.badgeLabel
    console.log('[macOS Dock Badge]', count);
    // Future: NativeModules.MacOSDock?.setBadgeCount(count);
  }

  addNotificationResponseListener(
    callback: (response: NotificationResponse) => void
  ): () => void {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== callback);
    };
  }

  /**
   * Internal method to dispatch notification responses.
   * Called by native code when user interacts with notification.
   */
  _handleNotificationResponse(response: NotificationResponse): void {
    this.listeners.forEach((listener) => {
      try {
        listener(response);
      } catch (error) {
        console.error('[macOS Notification] Listener error:', error);
      }
    });
  }
}

export const notificationService = new MacOSNotificationService();
