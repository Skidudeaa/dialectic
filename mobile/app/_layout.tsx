/**
 * ARCHITECTURE: Root layout with session and lock providers.
 * WHY: Centralized auth state management with biometric/PIN unlock support.
 * TRADEOFF: Nested providers add complexity but enable clean separation of concerns.
 */

import { useEffect } from 'react';
import {
  DarkTheme,
  DefaultTheme,
  ThemeProvider,
} from '@react-navigation/native';
import { Stack, useRouter, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View, ActivityIndicator, StyleSheet, Alert } from 'react-native';
import 'react-native-reanimated';

import { useColorScheme } from '@/hooks/use-color-scheme';
import { SessionProvider, useSession } from '@/contexts/session-context';
import { LockProvider, useLock } from '@/contexts/lock-context';
import { useBiometric } from '@/hooks/use-biometric';
import { usePresence } from '@/hooks/use-presence';
import { useSessionRestore } from '@/hooks/use-session-restore';
import { NotificationProvider } from '@/contexts/notification-context';

/**
 * Provider component that initializes presence tracking at app root.
 * Must be inside SessionProvider and LockProvider to have access to auth state.
 */
function PresenceProvider({ children }: { children: React.ReactNode }) {
  usePresence(); // Initialize presence tracking (inactivity timer, app lifecycle)
  return <>{children}</>;
}

function BiometricSetupPrompt() {
  const { shouldPromptBiometricSetup, dismissBiometricPrompt } = useLock();
  const { isAvailable, enable, getBiometricLabel } = useBiometric();

  useEffect(() => {
    if (shouldPromptBiometricSetup && isAvailable) {
      Alert.alert(
        `Enable ${getBiometricLabel()}?`,
        `Would you like to use ${getBiometricLabel()} to quickly unlock Dialectic?`,
        [
          {
            text: 'Not Now',
            style: 'cancel',
            onPress: dismissBiometricPrompt,
          },
          {
            text: 'Enable',
            onPress: async () => {
              await enable();
              dismissBiometricPrompt();
            },
          },
        ]
      );
    }
  }, [shouldPromptBiometricSetup, isAvailable]);

  return null;
}

function RootLayoutNav() {
  const { session, isLoading } = useSession();
  const { isLocked } = useLock();
  const { isReady: isDbReady, isRestoring, restoreNavigation, error: dbError } = useSessionRestore();
  const segments = useSegments();
  const router = useRouter();
  const colorScheme = useColorScheme();

  // Log database errors (non-fatal, app continues)
  useEffect(() => {
    if (dbError) {
      console.warn('[RootLayout] Database init error (non-fatal):', dbError.message);
    }
  }, [dbError]);

  useEffect(() => {
    if (isLoading) return;

    const inAuthGroup = segments[0] === '(auth)';
    const inAppGroup = segments[0] === '(app)';
    const isUnlockScreen = segments[1] === 'unlock';
    const isSetPinScreen = segments[1] === 'set-pin';

    if (!session) {
      // Not signed in - redirect to sign-in
      if (!inAuthGroup || isUnlockScreen || isSetPinScreen) {
        router.replace('/(auth)/sign-in');
      }
    } else if (isLocked) {
      // Signed in but locked - redirect to unlock
      if (!isUnlockScreen && !isSetPinScreen) {
        router.replace('/(auth)/unlock');
      }
    } else if (!session.user.emailVerified) {
      // Signed in but email not verified - redirect to verify
      if (segments[1] !== 'verify-email') {
        router.replace('/(auth)/verify-email');
      }
    } else {
      // Signed in, unlocked, and verified - redirect to app
      if (!inAppGroup) {
        router.replace('/(app)');
      }
    }
  }, [session, isLoading, isLocked, segments]);

  // Session restoration - runs AFTER auth routing settles
  useEffect(() => {
    if (
      isDbReady &&
      !isLoading &&
      session &&
      !isLocked &&
      session.user.emailVerified
    ) {
      restoreNavigation();
    }
  }, [isDbReady, isLoading, session, isLocked, restoreNavigation]);

  // Show loading screen while checking session or initializing database
  if (isLoading || isRestoring) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#3b82f6" />
      </View>
    );
  }

  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      <BiometricSetupPrompt />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(auth)" />
        <Stack.Screen name="(app)" />
        <Stack.Screen name="index" options={{ headerShown: false }} />
      </Stack>
      <StatusBar style="auto" />
    </ThemeProvider>
  );
}

export default function RootLayout() {
  return (
    <SessionProvider>
      <LockProvider>
        <NotificationProvider>
          <PresenceProvider>
            <RootLayoutNav />
          </PresenceProvider>
        </NotificationProvider>
      </LockProvider>
    </SessionProvider>
  );
}

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
