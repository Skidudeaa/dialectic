/**
 * macOS Keychain implementation of SecureStorage.
 *
 * ARCHITECTURE: Uses react-native-keychain to wrap macOS Keychain Services.
 * WHY: macOS Keychain provides secure, encrypted storage for sensitive data.
 * TRADEOFF: Each key stored as separate service (no bulk operations).
 */

import * as Keychain from 'react-native-keychain';
import type { SecureStorage } from '@dialectic/app';

/**
 * macOS Keychain implementation of SecureStorage.
 *
 * Each key is stored as a separate service in the Keychain with the prefix
 * "com.dialectic." for namespacing. Values are encrypted by macOS automatically.
 */
export const secureStorage: SecureStorage = {
  async setItem(key: string, value: string): Promise<void> {
    await Keychain.setGenericPassword(key, value, {
      service: `com.dialectic.${key}`,
      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    });
  },

  async getItem(key: string): Promise<string | null> {
    try {
      const result = await Keychain.getGenericPassword({
        service: `com.dialectic.${key}`,
      });
      if (result && typeof result === 'object' && 'password' in result) {
        return result.password;
      }
      return null;
    } catch {
      return null;
    }
  },

  async deleteItem(key: string): Promise<void> {
    await Keychain.resetGenericPassword({
      service: `com.dialectic.${key}`,
    });
  },

  async hasItem(key: string): Promise<boolean> {
    const value = await this.getItem(key);
    return value !== null;
  },
};
