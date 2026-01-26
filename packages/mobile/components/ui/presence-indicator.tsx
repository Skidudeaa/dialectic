/**
 * ARCHITECTURE: Presence indicator with dot and optional label.
 * WHY: CONTEXT.md specifies both dot indicator AND text label.
 * TRADEOFF: Slightly more visual noise vs clarity of status.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

type PresenceStatus = 'online' | 'away' | 'offline';

interface PresenceIndicatorProps {
  status: PresenceStatus;
  lastSeen?: string;
  showLabel?: boolean;
  size?: 'small' | 'medium' | 'large';
}

const STATUS_COLORS = {
  online: '#22c55e', // Green
  away: '#f59e0b', // Amber
  offline: '#9ca3af', // Gray
};

const STATUS_LABELS = {
  online: 'Online',
  away: 'Away',
  offline: 'Offline',
};

const DOT_SIZES = {
  small: 8,
  medium: 10,
  large: 12,
};

function formatLastSeen(isoTimestamp: string): string {
  const lastSeenDate = new Date(isoTimestamp);
  const now = new Date();
  const diffMs = now.getTime() - lastSeenDate.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);

  if (diffMins < 5) return 'Last seen recently';
  if (diffMins < 60) return `Last seen ${diffMins}m ago`;
  if (diffHours < 24) return 'Last seen today';
  return 'Last seen yesterday';
}

export function PresenceIndicator({
  status,
  lastSeen,
  showLabel = true,
  size = 'medium',
}: PresenceIndicatorProps) {
  const dotSize = DOT_SIZES[size];
  const color = STATUS_COLORS[status];

  // CONTEXT.md: Offline shows relative "last seen" time
  const getLabel = () => {
    if (status === 'offline' && lastSeen) {
      return formatLastSeen(lastSeen);
    }
    return STATUS_LABELS[status];
  };

  return (
    <View style={styles.container}>
      <View
        style={[
          styles.dot,
          {
            width: dotSize,
            height: dotSize,
            borderRadius: dotSize / 2,
            backgroundColor: color,
          },
        ]}
      />
      {showLabel && (
        <Text style={[styles.label, { color }]}>{getLabel()}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  dot: {},
  label: {
    fontSize: 12,
    fontWeight: '500',
  },
});
