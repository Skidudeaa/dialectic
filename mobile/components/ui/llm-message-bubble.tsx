/**
 * ARCHITECTURE: Centered message bubble for Claude responses.
 * WHY: CONTEXT.md specifies distinct visual treatment for LLM messages.
 * TRADEOFF: Separate component vs extending MessageBubble.
 */

import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { MarkdownContent } from './markdown-content';
import { ThinkingIndicator } from './thinking-indicator';

interface LLMMessageBubbleProps {
  content?: string;
  isThinking?: boolean;
  isStreaming?: boolean;
  partialContent?: string;
  createdAt?: string;
  onStopPress?: () => void;
}

export function LLMMessageBubble({
  content,
  isThinking = false,
  isStreaming = false,
  partialContent,
  createdAt,
  onStopPress,
}: LLMMessageBubbleProps) {
  // Display content: show partial during streaming, full content when done
  const displayContent = isStreaming ? partialContent : content;
  const showContent = displayContent && displayContent.length > 0;

  return (
    <View style={styles.container}>
      {/* Avatar/Label */}
      <View style={styles.header}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>C</Text>
        </View>
        <Text style={styles.label}>Claude</Text>
      </View>

      {/* Message Bubble */}
      <View style={styles.bubble}>
        {isThinking && !showContent ? (
          <ThinkingIndicator label={undefined} />
        ) : showContent ? (
          <MarkdownContent content={displayContent} isLLM />
        ) : null}

        {/* Streaming cursor indicator */}
        {isStreaming && showContent && <View style={styles.streamingCursor} />}
      </View>

      {/* Stop button during thinking/streaming - per CONTEXT.md */}
      {(isThinking || isStreaming) && onStopPress && (
        <TouchableOpacity style={styles.stopButton} onPress={onStopPress}>
          <Text style={styles.stopButtonText}>Stop</Text>
        </TouchableOpacity>
      )}

      {/* Timestamp */}
      {createdAt && !isThinking && !isStreaming && (
        <Text style={styles.timestamp}>
          {new Date(createdAt).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    // CONTEXT.md: Claude messages centered
    alignSelf: 'center',
    alignItems: 'center',
    maxWidth: '90%',
    marginVertical: 12,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  avatar: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#6366f1', // Indigo - Claude's color
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  avatarText: {
    color: '#ffffff',
    fontWeight: 'bold',
    fontSize: 14,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6366f1',
  },
  bubble: {
    // CONTEXT.md: Different bubble color for Claude
    backgroundColor: '#eef2ff', // Indigo-50
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 16,
    minWidth: 120,
    minHeight: 44,
  },
  streamingCursor: {
    width: 2,
    height: 16,
    backgroundColor: '#6366f1',
    marginLeft: 2,
    marginTop: 4,
    opacity: 0.7,
  },
  stopButton: {
    marginTop: 8,
    paddingVertical: 6,
    paddingHorizontal: 16,
    backgroundColor: '#fee2e2', // Red-100
    borderRadius: 12,
  },
  stopButtonText: {
    fontSize: 13,
    fontWeight: '500',
    color: '#dc2626', // Red-600
  },
  timestamp: {
    marginTop: 4,
    fontSize: 11,
    color: '#9ca3af',
  },
});
