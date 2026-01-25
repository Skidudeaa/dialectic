/**
 * ARCHITECTURE: Message bubble with delivery status via color.
 * WHY: CONTEXT.md specifies color-based status, more subtle than checkmarks.
 * TRADEOFF: Less explicit than checkmarks vs cleaner visual design.
 */

import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Pressable,
} from 'react-native';
import type { DeliveryStatus, Message } from '@/stores/messages-store';

interface MessageBubbleProps {
  message: Message;
  onRetry?: (clientId: string) => void;
  onPress?: () => void;
}

// CONTEXT.md: Subtle color change for delivery states (not checkmarks)
const DELIVERY_COLORS: Record<DeliveryStatus, string> = {
  sending: '#9ca3af', // Gray - sending
  sent: '#60a5fa', // Light blue - sent to server
  delivered: '#3b82f6', // Blue - delivered to recipient
  read: '#22c55e', // Green - read by recipient
  failed: '#ef4444', // Red - failed
};

export function MessageBubble({
  message,
  onRetry,
  onPress,
}: MessageBubbleProps) {
  const { content, isMine, deliveryStatus, createdAt, senderName, readBy } =
    message;

  const bubbleStyle = [
    styles.bubble,
    isMine ? styles.bubbleMine : styles.bubbleTheirs,
    isMine && { backgroundColor: DELIVERY_COLORS[deliveryStatus] },
  ];

  return (
    <Pressable
      onPress={onPress}
      style={[styles.container, isMine && styles.containerMine]}
    >
      {!isMine && senderName && (
        <Text style={styles.senderName}>{senderName}</Text>
      )}

      <View style={bubbleStyle}>
        <Text style={[styles.content, isMine && styles.contentMine]}>
          {content}
        </Text>

        <View style={styles.metadata}>
          <Text style={[styles.time, isMine && styles.timeMine]}>
            {formatTime(createdAt)}
          </Text>

          {/* CONTEXT.md: Read receipts show WHO read (not timestamp) */}
          {isMine && deliveryStatus === 'read' && readBy.length > 0 && (
            <Text style={[styles.readBy, isMine && styles.timeMine]}> Read</Text>
          )}
        </View>
      </View>

      {/* Failed message: red indicator + retry */}
      {deliveryStatus === 'failed' && (
        <TouchableOpacity
          onPress={() => onRetry?.(message.clientId || message.id)}
          style={styles.retryButton}
        >
          <Text style={styles.retryText}>Tap to retry</Text>
        </TouchableOpacity>
      )}
    </Pressable>
  );
}

function formatTime(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const styles = StyleSheet.create({
  container: {
    marginVertical: 4,
    marginHorizontal: 16,
    maxWidth: '80%',
    alignSelf: 'flex-start',
  },
  containerMine: {
    alignSelf: 'flex-end',
  },
  senderName: {
    fontSize: 12,
    color: '#6b7280',
    marginBottom: 2,
    marginLeft: 12,
  },
  bubble: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 18,
    minWidth: 60,
  },
  bubbleMine: {
    borderBottomRightRadius: 4,
  },
  bubbleTheirs: {
    backgroundColor: '#e5e7eb',
    borderBottomLeftRadius: 4,
  },
  content: {
    fontSize: 16,
    color: '#1f2937',
    lineHeight: 22,
  },
  contentMine: {
    color: '#ffffff',
  },
  metadata: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    marginTop: 4,
  },
  time: {
    fontSize: 11,
    color: '#6b7280',
  },
  timeMine: {
    color: 'rgba(255, 255, 255, 0.7)',
  },
  readBy: {
    fontSize: 11,
  },
  retryButton: {
    marginTop: 4,
    paddingVertical: 4,
    paddingHorizontal: 8,
    alignSelf: 'flex-end',
  },
  retryText: {
    fontSize: 12,
    color: '#ef4444',
    fontWeight: '500',
  },
});
