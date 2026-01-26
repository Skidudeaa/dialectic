import {
  setSecureStorageImplementation,
  setDatabaseImplementation,
  setNotificationServiceImplementation,
} from '@dialectic/app';
import { secureStorage, database, notificationService } from './services';

/**
 * ARCHITECTURE: Initialize platform-specific service implementations for Windows.
 * WHY: Registers Windows implementations of the abstract service interfaces.
 * TRADEOFF: Must be called once at app startup before using any services.
 *
 * This wires up:
 * - SecureStorage: Encrypted MMKV (TODO: Windows Credential Manager native module)
 * - Database: react-native-sqlite-2 with WebSQL API
 * - NotificationService: WinRT Toast notifications
 *
 * Call this function in App.tsx before rendering the main app content.
 */
export function initializePlatform(): void {
  setSecureStorageImplementation(secureStorage);
  setDatabaseImplementation(database);
  setNotificationServiceImplementation(notificationService);

  console.log('[Windows] Platform services initialized');
}
