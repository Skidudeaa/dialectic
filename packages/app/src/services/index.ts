/**
 * ARCHITECTURE: Barrel export for platform service abstractions.
 * WHY: Single import point for all service interfaces and utilities.
 * TRADEOFF: Re-exports add indirection but improve API ergonomics.
 */

// Platform detection
export {
  currentPlatform,
  isMobile,
  isDesktop,
  isWeb,
  modifierKey,
  type PlatformType,
} from './platform';

// Secure storage
export {
  type SecureStorage,
  setSecureStorageImplementation,
  getSecureStorage,
} from './secure-storage';

// Database
export {
  type Database,
  type DatabaseResult,
  type Transaction,
  setDatabaseImplementation,
  getDatabase,
} from './database';

// Notifications
export {
  type NotificationService,
  type NotificationContent,
  type NotificationPermission,
  type NotificationResponse,
  setNotificationServiceImplementation,
  getNotificationService,
} from './notifications';
