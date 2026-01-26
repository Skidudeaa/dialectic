/**
 * ARCHITECTURE: Inline connection status per CONTEXT.md.
 * WHY: Users need to know when messages are queued offline.
 * TRADEOFF: Takes up message list space vs clarity.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useWebSocketStore } from '@/stores/websocket-store';
import { offlineQueue } from '@/services/sync/offline-queue';

export function ConnectionStatus() {
  const { isConnected } = useWebSocketStore();
  const pendingCount = offlineQueue.getPending().length;

  if (isConnected && pendingCount === 0) {
    return null; // Don't show when connected with no pending
  }

  return (
    <View style={styles.container}>
      <View
        style={[
          styles.dot,
          isConnected ? styles.dotConnected : styles.dotDisconnected,
        ]}
      />
      <Text style={styles.text}>
        {isConnected
          ? `Sending ${pendingCount} queued message${pendingCount !== 1 ? 's' : ''}...`
          : 'Connection lost'}
      </Text>
    </View>
  );
}

// New messages divider for after reconnection
export function NewMessagesDivider() {
  return (
    <View style={styles.dividerContainer}>
      <View style={styles.dividerLine} />
      <Text style={styles.dividerText}>New messages</Text>
      <View style={styles.dividerLine} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
    paddingHorizontal: 16,
    backgroundColor: '#fef3c7',
    gap: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  dotConnected: {
    backgroundColor: '#22c55e',
  },
  dotDisconnected: {
    backgroundColor: '#ef4444',
  },
  text: {
    fontSize: 13,
    color: '#92400e',
    fontWeight: '500',
  },
  dividerContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 16,
    gap: 8,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: '#3b82f6',
  },
  dividerText: {
    fontSize: 12,
    color: '#3b82f6',
    fontWeight: '600',
  },
});
