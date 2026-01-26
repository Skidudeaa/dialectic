/**
 * ARCHITECTURE: Platform-agnostic secure storage interface.
 * WHY: Mobile uses expo-secure-store, desktop needs different implementations.
 * TRADEOFF: Registration pattern requires init call before use.
 *
 * Implementations:
 * - Mobile (iOS/Android): expo-secure-store
 * - macOS: react-native-keychain
 * - Windows: Custom native module (Windows Credential Manager)
 */

export interface SecureStorage {
  /**
   * Store a value securely.
   * @param key - Storage key
   * @param value - Value to store (will be encrypted)
   */
  setItem(key: string, value: string): Promise<void>;

  /**
   * Retrieve a securely stored value.
   * @param key - Storage key
   * @returns The stored value, or null if not found
   */
  getItem(key: string): Promise<string | null>;

  /**
   * Delete a securely stored value.
   * @param key - Storage key
   */
  deleteItem(key: string): Promise<void>;

  /**
   * Check if a key exists in secure storage.
   * @param key - Storage key
   */
  hasItem(key: string): Promise<boolean>;
}

// Placeholder - each platform provides its own implementation
let _secureStorage: SecureStorage | null = null;

export function setSecureStorageImplementation(impl: SecureStorage): void {
  _secureStorage = impl;
}

export function getSecureStorage(): SecureStorage {
  if (!_secureStorage) {
    throw new Error(
      'SecureStorage not initialized. Call setSecureStorageImplementation first.'
    );
  }
  return _secureStorage;
}
