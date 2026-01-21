/**
 * ARCHITECTURE: Auth route group layout with minimal header.
 * WHY: Clean auth flow presentation without navigation clutter.
 * TRADEOFF: No back navigation header, but screens provide their own links.
 */

import { Stack } from 'expo-router';

export default function AuthLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="sign-in" />
      <Stack.Screen name="sign-up" />
      <Stack.Screen name="verify-email" />
      <Stack.Screen name="forgot-password" />
      <Stack.Screen name="reset-password" />
      <Stack.Screen name="unlock" />
      <Stack.Screen name="set-pin" />
    </Stack>
  );
}
