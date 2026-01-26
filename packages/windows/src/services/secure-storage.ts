import { SecureStorage } from '@dialectic/app';

/**
 * Windows secure storage implementation using encrypted MMKV.
 *
 * ARCHITECTURE: Uses MMKV with encryption for key-value storage.
 * WHY: react-native-keychain has NO Windows support. MMKV is the best
 *      cross-platform alternative with encryption capabilities.
 * TRADEOFF: This is NOT as secure as Windows Credential Manager.
 *           MMKV encrypts data but stores the key in the app sandbox.
 *           For production, implement native module using Windows.Security.Credentials.PasswordVault
 *
 * TODO: Create native C++ module for Windows.Security.Credentials.PasswordVault
 *       for true OS-level secure storage.
 */

/**
 * MMKV wrapper interface with delete method.
 * The actual MMKV library uses 'delete' which is a reserved word issue.
 */
interface MMKVStorage {
  set(key: string, value: string): void;
  getString(key: string): string | undefined;
  delete(key: string): void;
  contains(key: string): boolean;
}

// Lazy-initialized MMKV instance
let storage: MMKVStorage | null = null;

function getStorage(): MMKVStorage {
  if (!storage) {
    // Dynamic import to avoid instantiation at module load time
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { MMKV } = require('react-native-mmkv');
    storage = new MMKV({
      id: 'dialectic-secure',
      encryptionKey: 'dialectic-encryption-key-windows', // Should be dynamically generated in production
    }) as MMKVStorage;
  }
  return storage;
}

export const secureStorage: SecureStorage = {
  async setItem(key: string, value: string): Promise<void> {
    getStorage().set(key, value);
  },

  async getItem(key: string): Promise<string | null> {
    const value = getStorage().getString(key);
    return value ?? null;
  },

  async deleteItem(key: string): Promise<void> {
    getStorage().delete(key);
  },

  async hasItem(key: string): Promise<boolean> {
    return getStorage().contains(key);
  },
};
