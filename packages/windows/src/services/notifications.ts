import {
  NotificationService,
  NotificationContent,
  NotificationPermission,
  NotificationResponse,
} from '@dialectic/app';

/**
 * ARCHITECTURE: Windows notification service using WinRT Toast API.
 * WHY: Windows notifications use WinRT Windows.UI.Notifications namespace.
 * TRADEOFF: react-native-winrt provides access but may require configuration.
 *
 * Note: react-native-winrt provides Windows.UI.Notifications access for
 * showing Toast notifications that appear in the Action Center.
 */

// Import WinRT types for Windows notifications dynamically
// Note: react-native-winrt provides Windows.UI.Notifications access
let ToastNotificationManager: any;
let ToastNotification: any;
let ToastTemplateType: any;

try {
  const winrt = require('react-native-winrt');
  ToastNotificationManager = winrt.Windows?.UI?.Notifications?.ToastNotificationManager;
  ToastNotification = winrt.Windows?.UI?.Notifications?.ToastNotification;
  ToastTemplateType = winrt.Windows?.UI?.Notifications?.ToastTemplateType;
} catch (e) {
  console.warn('[WindowsNotifications] WinRT not available, notifications will be logged only');
}

class WindowsNotificationService implements NotificationService {
  private listeners: Array<(response: NotificationResponse) => void> = [];
  private notifier: any = null;

  private getNotifier() {
    if (!this.notifier && ToastNotificationManager) {
      try {
        this.notifier = ToastNotificationManager.createToastNotifier();
      } catch (e) {
        console.warn('[WindowsNotifications] Failed to create notifier:', e);
      }
    }
    return this.notifier;
  }

  async requestPermissions(): Promise<NotificationPermission> {
    // Windows notifications are controlled by system settings
    // Apps don't need to explicitly request permission like on mobile
    return { granted: true, canAskAgain: false };
  }

  async getPermissions(): Promise<NotificationPermission> {
    // Windows doesn't have a permission API like mobile platforms
    return { granted: true, canAskAgain: false };
  }

  async showNotification(content: NotificationContent): Promise<string> {
    const id = `notification-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    if (!ToastNotificationManager) {
      // Fallback: log notification when WinRT not available
      console.log('[Windows Notification]', content.title, content.body);
      return id;
    }

    try {
      // Get toast template with two text fields (title + body)
      // ToastTemplateType.toastText02 provides two text lines
      const template = ToastNotificationManager.getTemplateContent(
        ToastTemplateType.toastText02
      );

      // Set title and body text
      const textNodes = template.getElementsByTagName('text');
      textNodes.item(0).appendChild(template.createTextNode(content.title));
      textNodes.item(1).appendChild(template.createTextNode(content.body));

      // Create and show toast notification
      const toast = new ToastNotification(template);
      this.getNotifier()?.show(toast);
    } catch (error) {
      console.error('[WindowsNotifications] Failed to show notification:', error);
    }

    return id;
  }

  async cancelNotification(id: string): Promise<void> {
    // Toast dismissal is not straightforward in WinRT - toasts auto-dismiss
    // or user can dismiss from Action Center
    console.log('[WindowsNotifications] Cancel not implemented:', id);
  }

  async setBadgeCount(count: number): Promise<void> {
    // Windows badge requires BadgeNotification from WinRT
    // This would need XML badge content - more complex setup
    // For now, log and defer to system tray unread count
    console.log('[WindowsNotifications] Badge count:', count);
  }

  addNotificationResponseListener(
    callback: (response: NotificationResponse) => void
  ): () => void {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== callback);
    };
  }

  // Internal: dispatch to listeners when notification tapped
  private dispatchResponse(response: NotificationResponse): void {
    this.listeners.forEach((listener) => listener(response));
  }
}

export const notificationService = new WindowsNotificationService();
