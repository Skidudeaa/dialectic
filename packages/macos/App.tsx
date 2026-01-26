/**
 * Dialectic for macOS
 *
 * ARCHITECTURE: Minimal bootstrap app for macOS platform.
 * WHY: Bare workflow required for react-native-macos (no Expo support).
 * TRADEOFF: Separate entry point vs code sharing - needed for platform init.
 */

import React from 'react';
import { View, Text, StyleSheet, Platform } from 'react-native';

export default function App() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Dialectic for macOS</Text>
      <Text style={styles.subtitle}>
        Platform: {Platform.OS} ({Platform.Version})
      </Text>
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
});
