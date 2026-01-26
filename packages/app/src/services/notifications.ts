/**
 * ARCHITECTURE: Platform-agnostic notification service interface.
 * WHY: Mobile uses expo-notifications, desktop needs native notification APIs.
 * TRADEOFF: Push registration is optional (desktop may not support).
 *
 * Implementations:
 * - Mobile: expo-notifications
 * - macOS: Native NSUserNotification via react-native module
 * - Windows: react-native-winrt with Windows.UI.Notifications
 */

export interface NotificationContent {
  title: string;
  body: string;
  data?: Record<string, unknown>;
  badge?: number;
  sound?: boolean;
}

export interface NotificationPermission {
  granted: boolean;
  canAskAgain: boolean;
}

export interface NotificationService {
  /**
   * Request notification permissions.
   */
  requestPermissions(): Promise<NotificationPermission>;

  /**
   * Check current notification permission status.
   */
  getPermissions(): Promise<NotificationPermission>;

  /**
   * Display a local notification.
   */
  showNotification(content: NotificationContent): Promise<string>;

  /**
   * Cancel a scheduled/displayed notification.
   * @param id - Notification ID returned from showNotification
   */
  cancelNotification(id: string): Promise<void>;

  /**
   * Set app badge count.
   * @param count - Badge number (0 to clear)
   */
  setBadgeCount(count: number): Promise<void>;

  /**
   * Register for remote push notifications.
   * Optional - desktop may not support push.
   * @returns Push token for server registration
   */
  registerForPushNotifications?(): Promise<string>;

  /**
   * Add listener for notification interactions.
   * @param callback - Called when user taps notification
   * @returns Unsubscribe function
   */
  addNotificationResponseListener(
    callback: (response: NotificationResponse) => void
  ): () => void;
}

export interface NotificationResponse {
  notificationId: string;
  actionId?: string;
  data?: Record<string, unknown>;
}

// Registration pattern
let _notificationService: NotificationService | null = null;

export function setNotificationServiceImplementation(impl: NotificationService): void {
  _notificationService = impl;
}

export function getNotificationService(): NotificationService {
  if (!_notificationService) {
    throw new Error(
      'NotificationService not initialized. Call setNotificationServiceImplementation first.'
    );
  }
  return _notificationService;
}
