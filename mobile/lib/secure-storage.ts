/**
 * ARCHITECTURE: Typed wrapper around expo-secure-store.
 * WHY: Single abstraction for all secure storage operations with typed keys.
 * TRADEOFF: Slight overhead vs direct SecureStore calls, but better DX and refactorability.
 */

import * as SecureStore from 'expo-secure-store';

const KEYS = {
  SESSION: 'dialectic_session',
  BIOMETRIC_ENABLED: 'dialectic_biometric_enabled',
  LAST_ACTIVE: 'dialectic_last_active',
} as const;

export const secureStorage = {
  async setSession(session: object): Promise<void> {
    await SecureStore.setItemAsync(KEYS.SESSION, JSON.stringify(session));
  },

  async getSession<T>(): Promise<T | null> {
    const value = await SecureStore.getItemAsync(KEYS.SESSION);
    return value ? JSON.parse(value) : null;
  },

  async deleteSession(): Promise<void> {
    await SecureStore.deleteItemAsync(KEYS.SESSION);
  },

  async setBiometricEnabled(enabled: boolean): Promise<void> {
    await SecureStore.setItemAsync(KEYS.BIOMETRIC_ENABLED, String(enabled));
  },

  async getBiometricEnabled(): Promise<boolean> {
    const value = await SecureStore.getItemAsync(KEYS.BIOMETRIC_ENABLED);
    return value === 'true';
  },

  async setLastActive(timestamp: number): Promise<void> {
    await SecureStore.setItemAsync(KEYS.LAST_ACTIVE, String(timestamp));
  },

  async getLastActive(): Promise<number | null> {
    const value = await SecureStore.getItemAsync(KEYS.LAST_ACTIVE);
    return value ? parseInt(value, 10) : null;
  },
};
