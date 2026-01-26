/**
 * ARCHITECTURE: Room index screen - placeholder for room view.
 * WHY: Required for expo-router dynamic route structure.
 * TRADEOFF: Minimal placeholder until full room screen implementation.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useLocalSearchParams } from 'expo-router';

export default function RoomScreen() {
  const { roomId } = useLocalSearchParams<{ roomId: string }>();

  return (
    <View style={styles.container}>
      <Text style={styles.text}>Room: {roomId}</Text>
      <Text style={styles.subtext}>Select a thread to start chatting</Text>
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
