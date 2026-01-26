/**
 * ARCHITECTURE: Individual thread node card for cladogram visualization.
 * WHY: Displays thread metadata (title, count, date) in a pressable card.
 * TRADEOFF: Fixed dimensions for layout predictability vs responsive sizing.
 */

import React from 'react';
import { Pressable, Text, StyleSheet } from 'react-native';
import type { ThreadNode } from '@/hooks/use-genealogy';

interface ThreadNodeViewProps {
  node: ThreadNode;
  onPress: () => void;
  isCurrentThread?: boolean;
}

export const NODE_WIDTH = 150;
export const NODE_HEIGHT = 60;

export function ThreadNodeView({
  node,
  onPress,
  isCurrentThread = false,
}: ThreadNodeViewProps) {
  const displayTitle = node.title || 'Untitled';
  const dateStr = new Date(node.created_at).toLocaleDateString();

  return (
    <Pressable
      style={[
        styles.nodeContainer,
        isCurrentThread && styles.currentNode,
      ]}
      onPress={onPress}
    >
      <Text style={styles.nodeTitle} numberOfLines={1}>
        {displayTitle}
      </Text>
      <Text style={styles.nodeSubtitle}>
        {node.message_count} messages
      </Text>
      <Text style={styles.nodeTimestamp}>
        {dateStr}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  nodeContainer: {
    width: NODE_WIDTH,
    height: NODE_HEIGHT,
    backgroundColor: '#ffffff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e2e8f0',
    padding: 8,
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  currentNode: {
    borderColor: '#6366f1',
    borderWidth: 2,
    backgroundColor: '#eef2ff',
  },
  nodeTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: '#1e293b',
  },
  nodeSubtitle: {
    fontSize: 11,
    color: '#64748b',
    marginTop: 2,
  },
  nodeTimestamp: {
    fontSize: 10,
    color: '#94a3b8',
    marginTop: 2,
  },
});
