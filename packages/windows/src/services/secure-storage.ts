import { MMKV } from 'react-native-mmkv';
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

// Create encrypted MMKV instance for secure storage
// Note: MMKV Windows support may be experimental - test thoroughly
const storage = new MMKV({
  id: 'dialectic-secure',
  encryptionKey: 'dialectic-encryption-key-windows', // Should be dynamically generated in production
});

export const secureStorage: SecureStorage = {
  async setItem(key: string, value: string): Promise<void> {
    storage.set(key, value);
  },

  async getItem(key: string): Promise<string | null> {
    const value = storage.getString(key);
    return value ?? null;
  },

  async deleteItem(key: string): Promise<void> {
    storage.delete(key);
  },

  async hasItem(key: string): Promise<boolean> {
    return storage.contains(key);
  },
};
