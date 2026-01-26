/**
 * ARCHITECTURE: Centered message bubble for Claude responses with interjection UX.
 * WHY: CONTEXT.md specifies distinct visual treatment for LLM messages.
 * TRADEOFF: Separate component vs extending MessageBubble for clear separation.
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
  // Interjection metadata
  speakerType?: 'llm_primary' | 'llm_provoker' | 'LLM_PRIMARY' | 'LLM_PROVOKER' | null;
  interjectionType?: 'summoned' | 'proactive' | null;
  onStopPress?: () => void;
}

// CONTEXT.md: Provoker persona "Claude *" (asterisk denotes destabilizer mode)
const getPersonaName = (speakerType: string | null | undefined): string => {
  if (
    speakerType === 'llm_provoker' ||
    speakerType === 'LLM_PROVOKER'
  ) {
    return 'Claude *';
  }
  return 'Claude';
};

const isProvokerMode = (speakerType: string | null | undefined): boolean => {
  return (
    speakerType === 'llm_provoker' ||
    speakerType === 'LLM_PROVOKER'
  );
};

export function LLMMessageBubble({
  content,
  isThinking = false,
  isStreaming = false,
  partialContent,
  createdAt,
  speakerType,
  interjectionType,
  onStopPress,
}: LLMMessageBubbleProps) {
  // Display content: show partial during streaming, full content when done
  const displayContent = isStreaming ? partialContent : content;
  const showContent = displayContent && displayContent.length > 0;

  const personaName = getPersonaName(speakerType);
  const isProvoker = isProvokerMode(speakerType);
  const isProactive = interjectionType === 'proactive';

  return (
    <View style={styles.container}>
      {/* Header with persona and interjection indicator */}
      <View style={styles.header}>
        <View style={[styles.avatar, isProvoker && styles.provokerAvatar]}>
          <Text style={styles.avatarText}>
            {isProvoker ? '*' : 'C'}
          </Text>
        </View>
        <Text style={[styles.label, isProvoker && styles.provokerLabel]}>
          {personaName}
        </Text>

        {/* CONTEXT.md: Subtle indicator for proactive interjections */}
        {isProactive && (
          <View style={styles.unpromptedBadge}>
            <Text style={styles.unpromptedText}>unprompted</Text>
          </View>
        )}
      </View>

      {/* Message Bubble */}
      <View style={[styles.bubble, isProvoker && styles.provokerBubble]}>
        {isThinking && !showContent ? (
          <ThinkingIndicator label={undefined} />
        ) : showContent ? (
          <MarkdownContent content={displayContent} isLLM />
        ) : null}

        {/* Streaming cursor indicator */}
        {isStreaming && showContent && (
          <View style={[styles.streamingCursor, isProvoker && styles.provokerCursor]} />
        )}
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
  provokerAvatar: {
    backgroundColor: '#f59e0b', // Amber for provoker
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
  provokerLabel: {
    color: '#f59e0b',
  },
  unpromptedBadge: {
    marginLeft: 8,
    backgroundColor: '#f1f5f9',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  unpromptedText: {
    fontSize: 10,
    color: '#64748b',
    fontStyle: 'italic',
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
  provokerBubble: {
    backgroundColor: '#fef3c7', // Amber-50
  },
  streamingCursor: {
    width: 2,
    height: 16,
    backgroundColor: '#6366f1',
    marginLeft: 2,
    marginTop: 4,
    opacity: 0.7,
  },
  provokerCursor: {
    backgroundColor: '#f59e0b',
  },
  stopButton: {
    marginTop: 8,
    paddingVertical: 6,
    paddingHorizontal: 16,
    backgroundColor: '#ef4444', // Red-500 for more prominent stop
    borderRadius: 12,
  },
  stopButtonText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#ffffff',
  },
  timestamp: {
    marginTop: 4,
    fontSize: 11,
    color: '#9ca3af',
  },
});
