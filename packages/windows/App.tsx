import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { initializePlatform } from './src/platform-init';

/**
 * Main App component for Dialectic Windows.
 *
 * Initializes platform services on startup before rendering content.
 * This ensures secure storage, database, and notifications are available
 * before any shared code from @dialectic/app attempts to use them.
 */
export default function App() {
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    // Initialize Windows platform services
    initializePlatform();
    setInitialized(true);
  }, []);

  if (!initialized) {
    return (
      <View style={styles.container}>
        <Text style={styles.loadingText}>Loading...</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.text}>Dialectic for Windows</Text>
      <Text style={styles.subtext}>Platform services initialized</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#fff',
  },
  text: {
    fontSize: 24,
    color: '#000',
    fontWeight: '600',
  },
  subtext: {
    fontSize: 14,
    color: '#666',
    marginTop: 8,
  },
  loadingText: {
    fontSize: 16,
    color: '#999',
  },
});
