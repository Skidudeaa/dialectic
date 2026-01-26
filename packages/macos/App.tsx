/**
 * Dialectic for macOS
 *
 * ARCHITECTURE: Bootstrap app with platform service initialization.
 * WHY: Bare workflow required for react-native-macos (no Expo support).
 * TRADEOFF: Separate entry point vs code sharing - needed for platform init.
 */

import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Platform } from 'react-native';
import { initializePlatform } from './src/platform-init';

export default function App() {
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    // Initialize platform-specific services before rendering main content
    initializePlatform();
    setInitialized(true);
  }, []);

  if (!initialized) {
    return (
      <View style={styles.container}>
        <Text style={styles.subtitle}>Loading...</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Dialectic for macOS</Text>
      <Text style={styles.subtitle}>
        Platform: {Platform.OS} ({Platform.Version})
      </Text>
      <Text style={styles.status}>Platform services initialized</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#1a1a2e',
  },
  title: {
    fontSize: 32,
    fontWeight: '600',
    color: '#ffffff',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: '#a0a0a0',
  },
  status: {
    fontSize: 14,
    color: '#6366f1',
    marginTop: 16,
  },
});
