/**
 * ARCHITECTURE: Thread screen - placeholder for thread conversation view.
 * WHY: Required for expo-router dynamic route structure.
 * TRADEOFF: Minimal placeholder until full thread screen implementation.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useLocalSearchParams } from 'expo-router';

export default function ThreadScreen() {
  const { roomId, threadId } = useLocalSearchParams<{
    roomId: string;
    threadId: string;
  }>();

  return (
    <View style={styles.container}>
      <Text style={styles.text}>Thread: {threadId}</Text>
      <Text style={styles.subtext}>Room: {roomId}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f8fafc',
  },
  text: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1e293b',
  },
  subtext: {
    marginTop: 8,
    fontSize: 14,
    color: '#64748b',
  },
});
