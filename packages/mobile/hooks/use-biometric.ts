/**
 * ARCHITECTURE: Hook for biometric authentication using expo-local-authentication.
 * WHY: Provides device biometric availability check, authentication trigger, and enable/disable.
 * TRADEOFF: Requires hardware enrollment - falls back to PIN for devices without biometrics.
 */

import { useState, useEffect, useCallback } from 'react';
import * as LocalAuthentication from 'expo-local-authentication';
import { secureStorage } from '@/lib/secure-storage';

interface BiometricState {
  isAvailable: boolean;
  isEnabled: boolean;
  biometricType: LocalAuthentication.AuthenticationType | null;
  isLoading: boolean;
}

export function useBiometric() {
  const [state, setState] = useState<BiometricState>({
    isAvailable: false,
    isEnabled: false,
    biometricType: null,
    isLoading: true,
  });

  useEffect(() => {
    checkBiometric();
  }, []);

  async function checkBiometric() {
    try {
      const hasHardware = await LocalAuthentication.hasHardwareAsync();
      const isEnrolled = await LocalAuthentication.isEnrolledAsync();
      const supportedTypes =
        await LocalAuthentication.supportedAuthenticationTypesAsync();
      const isEnabled = await secureStorage.getBiometricEnabled();

      setState({
        isAvailable: hasHardware && isEnrolled,
        isEnabled,
        biometricType: supportedTypes[0] ?? null,
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to check biometric:', error);
      setState((prev) => ({ ...prev, isLoading: false }));
    }
  }

  const authenticate = useCallback(async (): Promise<boolean> => {
    if (!state.isAvailable) return false;

    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Unlock Dialectic',
      fallbackLabel: 'Use PIN',
      cancelLabel: 'Cancel',
      disableDeviceFallback: true, // We handle PIN fallback ourselves
    });

    return result.success;
  }, [state.isAvailable]);

  const enable = useCallback(async () => {
    await secureStorage.setBiometricEnabled(true);
    setState((prev) => ({ ...prev, isEnabled: true }));
  }, []);

  const disable = useCallback(async () => {
    await secureStorage.setBiometricEnabled(false);
    setState((prev) => ({ ...prev, isEnabled: false }));
  }, []);

  const getBiometricLabel = useCallback(() => {
    if (!state.biometricType) return 'Biometric';
    switch (state.biometricType) {
      case LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION:
        return 'Face ID';
      case LocalAuthentication.AuthenticationType.FINGERPRINT:
        return 'Fingerprint';
      case LocalAuthentication.AuthenticationType.IRIS:
        return 'Iris';
      default:
        return 'Biometric';
    }
  }, [state.biometricType]);

  return {
    ...state,
    authenticate,
    enable,
    disable,
    getBiometricLabel,
    refresh: checkBiometric,
  };
}
