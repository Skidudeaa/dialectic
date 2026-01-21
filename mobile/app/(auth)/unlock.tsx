/**
 * ARCHITECTURE: Unlock screen with biometric + PIN fallback.
 * WHY: Per CONTEXT.md, users unlock with biometric after 15-min timeout, fallback to PIN.
 * TRADEOFF: 3 biometric attempts before PIN fallback - balances security vs UX.
 */

import { View, Text, StyleSheet, Pressable, Alert } from 'react-native';
import { useState, useEffect, useCallback } from 'react';
import { router } from 'expo-router';

import { PinInput } from '@/components/auth';
import { useBiometric } from '@/hooks/use-biometric';
import { useLock } from '@/contexts/lock-context';
import { useSession } from '@/contexts/session-context';
import { useThemeColor } from '@/hooks/use-theme-color';

const MAX_BIOMETRIC_ATTEMPTS = 3;

export default function UnlockScreen() {
  const { isAvailable, isEnabled, authenticate, getBiometricLabel } =
    useBiometric();
  const { unlock, verifyPin, pinHash } = useLock();
  const { session, signOut } = useSession();
  const [biometricAttempts, setBiometricAttempts] = useState(0);
  const [showPinFallback, setShowPinFallback] = useState(false);
  const [pinError, setPinError] = useState<string | undefined>();
  const textColor = useThemeColor({}, 'text');
  const backgroundColor = useThemeColor({}, 'background');

  // Auto-attempt biometric on mount if available and enabled
  useEffect(() => {
    if (isAvailable && isEnabled && biometricAttempts === 0) {
      attemptBiometric();
    } else if (!isAvailable || !isEnabled) {
      setShowPinFallback(true);
    }
  }, [isAvailable, isEnabled]);

  const attemptBiometric = useCallback(async () => {
    if (biometricAttempts >= MAX_BIOMETRIC_ATTEMPTS) {
      setShowPinFallback(true);
      return;
    }

    const success = await authenticate();
    if (success) {
      unlock();
    } else {
      const newAttempts = biometricAttempts + 1;
      setBiometricAttempts(newAttempts);
      if (newAttempts >= MAX_BIOMETRIC_ATTEMPTS) {
        setShowPinFallback(true);
      }
    }
  }, [biometricAttempts, authenticate, unlock]);

  const handlePinComplete = (pin: string) => {
    if (verifyPin(pin)) {
      unlock();
    } else {
      setPinError('Incorrect PIN');
      setTimeout(() => setPinError(undefined), 2000);
    }
  };

  const handleSignOut = async () => {
    Alert.alert(
      'Sign Out',
      'Are you sure you want to sign out? You will need to log in again.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Sign Out',
          style: 'destructive',
          onPress: async () => {
            await signOut();
          },
        },
      ]
    );
  };

  // If no PIN is set and biometric failed, show option to set PIN or sign out
  const noPinAvailable = !pinHash && showPinFallback;

  return (
    <View style={[styles.container, { backgroundColor }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: textColor }]}>
          Unlock Dialectic
        </Text>
        <Text style={[styles.subtitle, { color: textColor }]}>
          {session?.user.email}
        </Text>
      </View>

      {showPinFallback && !noPinAvailable ? (
        <PinInput
          label="Enter your PIN"
          onComplete={handlePinComplete}
          error={pinError}
        />
      ) : noPinAvailable ? (
        <View style={styles.noPinContainer}>
          <Text style={[styles.noPinText, { color: textColor }]}>
            No PIN set. Please set up a PIN or sign out to continue.
          </Text>
          <Pressable
            style={styles.setupPinButton}
            onPress={() => router.push('/(auth)/set-pin')}
          >
            <Text style={styles.setupPinText}>Set Up PIN</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.biometricContainer}>
          <Pressable style={styles.biometricButton} onPress={attemptBiometric}>
            <Text style={styles.biometricIcon}>
              {getBiometricLabel() === 'Face ID' ? '\uD83D\uDC64' : '\uD83D\uDC46'}
            </Text>
            <Text style={[styles.biometricLabel, { color: textColor }]}>
              Tap to use {getBiometricLabel()}
            </Text>
          </Pressable>

          {biometricAttempts > 0 && (
            <Pressable onPress={() => setShowPinFallback(true)}>
              <Text style={styles.usePinLink}>Use PIN instead</Text>
            </Pressable>
          )}
        </View>
      )}

      <Pressable style={styles.signOutLink} onPress={handleSignOut}>
        <Text style={styles.signOutText}>Sign out</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingHorizontal: 24,
    justifyContent: 'center',
  },
  header: {
    alignItems: 'center',
    marginBottom: 48,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 14,
    opacity: 0.7,
  },
  biometricContainer: {
    alignItems: 'center',
  },
  biometricButton: {
    alignItems: 'center',
    padding: 32,
  },
  biometricIcon: {
    fontSize: 64,
    marginBottom: 16,
  },
  biometricLabel: {
    fontSize: 16,
  },
  usePinLink: {
    color: '#3b82f6',
    fontSize: 14,
    marginTop: 24,
  },
  noPinContainer: {
    alignItems: 'center',
    paddingHorizontal: 24,
  },
  noPinText: {
    textAlign: 'center',
    fontSize: 14,
    marginBottom: 24,
    opacity: 0.7,
  },
  setupPinButton: {
    backgroundColor: '#3b82f6',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  setupPinText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  signOutLink: {
    position: 'absolute',
    bottom: 48,
    alignSelf: 'center',
  },
  signOutText: {
    color: '#ef4444',
    fontSize: 14,
  },
});
