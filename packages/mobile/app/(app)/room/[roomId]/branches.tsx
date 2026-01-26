/**
 * ARCHITECTURE: Branches screen showing thread genealogy as cladogram.
 * WHY: Visual navigation of thread tree helps users understand conversation structure.
 * TRADEOFF: Dedicated screen vs inline view for focus and full-screen visualization.
 */

import React from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { useLocalSearchParams, Stack } from 'expo-router';
import { CladogramView } from '@/components/branches/cladogram-view';
import { useGenealogy } from '@/hooks/use-genealogy';

export default function BranchesScreen() {
  const { roomId, threadId } = useLocalSearchParams<{
    roomId: string;
    threadId?: string;
  }>();

  const { data: roots, isLoading, error } = useGenealogy(roomId);

  if (isLoading) {
    return (
      <>
        <Stack.Screen
          options={{
            title: 'Branches',
            headerBackTitle: 'Back',
          }}
        />
        <View style={styles.centerContainer}>
          <ActivityIndicator size="large" color="#6366f1" />
          <Text style={styles.loadingText}>Loading branches...</Text>
        </View>
      </>
    );
  }

  if (error) {
    return (
      <>
        <Stack.Screen
          options={{
            title: 'Branches',
            headerBackTitle: 'Back',
          }}
        />
        <View style={styles.centerContainer}>
          <Text style={styles.errorText}>Failed to load branches</Text>
        </View>
      </>
    );
  }

  if (!roots || roots.length === 0) {
    return (
      <>
        <Stack.Screen
          options={{
            title: 'Branches',
            headerBackTitle: 'Back',
          }}
        />
        <View style={styles.centerContainer}>
          <Text style={styles.emptyText}>No branches yet</Text>
          <Text style={styles.emptySubtext}>
            Fork from any message to create a branch
          </Text>
        </View>
      </>
    );
  }

  return (
    <>
      <Stack.Screen
        options={{
          title: 'Branches',
          headerBackTitle: 'Back',
        }}
      />
      <CladogramView
        roots={roots}
        roomId={roomId!}
        currentThreadId={threadId}
      />
    </>
  );
}

const styles = StyleSheet.create({
  centerContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f8fafc',
  },
  loadingText: {
    marginTop: 12,
    fontSize: 16,
    color: '#64748b',
  },
  errorText: {
    fontSize: 16,
    color: '#ef4444',
  },
  emptyText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#64748b',
  },
  emptySubtext: {
    marginTop: 8,
    fontSize: 14,
    color: '#94a3b8',
    textAlign: 'center',
    paddingHorizontal: 40,
  },
});
