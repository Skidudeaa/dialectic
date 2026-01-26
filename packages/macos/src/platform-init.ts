/**
 * Platform initialization for macOS.
 *
 * ARCHITECTURE: Registers platform-specific service implementations with @dialectic/app.
 * WHY: macOS cannot use Expo modules, so we provide alternative implementations.
 * TRADEOFF: Must call initializePlatform() before any service usage.
 */

import {
  setSecureStorageImplementation,
  setDatabaseImplementation,
  setNotificationServiceImplementation,
} from '@dialectic/app';
import { secureStorage, database, notificationService } from './services';

/**
 * Initialize platform-specific service implementations for macOS.
 *
 * Call this once at app startup before using any services.
 * Typically called in App.tsx useEffect.
 */
export function initializePlatform(): void {
  // Register Keychain-based secure storage
  setSecureStorageImplementation(secureStorage);

  // Register SQLite database
  setDatabaseImplementation(database);

  // Register notification service (placeholder until native module added)
  setNotificationServiceImplementation(notificationService);

  console.log('[macOS] Platform services initialized');
}
