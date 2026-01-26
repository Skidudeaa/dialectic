/**
 * ARCHITECTURE: FlashList for performant message rendering with scroll position maintenance.
 * WHY: FlatList has scroll jump issues during upward pagination; FlashList handles this.
 * TRADEOFF: Additional dependency vs custom solution, but FlashList is battle-tested.
 */

import React, { useCallback, useRef, useEffect } from 'react';
import { View, StyleSheet, ActivityIndicator, Text } from 'react-native';
import { FlashList } from '@shopify/flash-list';
import type { ListRenderItemInfo, FlashListRef } from '@shopify/flash-list';
import { MessageBubble } from '@/components/ui/message-bubble';
import { LLMMessageBubble } from '@/components/ui/llm-message-bubble';
import { MessageContextMenu } from './message-context-menu';
import type { Message } from '@/stores/messages-store';
import { useSessionStore } from '@/stores/session-store';
import { useLLM } from '@/hooks/use-llm';

interface MessageListProps {
  threadId: string;
  roomId: string;
  messages: Message[];
  isLoading: boolean;
  isLoadingOlder: boolean;
  hasMoreOlder: boolean;
  onLoadOlder: () => Promise<void>;
  /** Called when scroll position changes significantly */
  onScrollPositionChange?: (position: { offset: number; messageId?: string }) => void;
}

const LOAD_OLDER_THRESHOLD = 0.3; // Trigger when 30% from top
const APPROXIMATE_ITEM_SIZE = 80; // For scroll position approximation

export function MessageList({
  threadId,
  roomId,
  messages,
  isLoading,
  isLoadingOlder,
  hasMoreOlder,
  onLoadOlder,
  onScrollPositionChange,
}: MessageListProps) {
  const listRef = useRef<FlashListRef<Message>>(null);
  const { getScrollPosition, setScrollPosition } = useSessionStore();
  const isInitialMount = useRef(true);

  // Get LLM stream state for this thread
  const {
    isThinking,
    isStreaming,
    partialResponse,
    speakerType: streamSpeakerType,
    interjectionType: streamInterjectionType,
    cancel,
  } = useLLM({ threadId });

  // Restore scroll position on mount
  useEffect(() => {
    if (isInitialMount.current && messages.length > 0) {
      const savedPosition = getScrollPosition(threadId);
      if (savedPosition) {
        // If we have a messageId, try to scroll to it
        if (savedPosition.messageId) {
          const index = messages.findIndex((m) => m.id === savedPosition.messageId);
          if (index !== -1) {
            // Small delay to ensure list is rendered
            setTimeout(() => {
              listRef.current?.scrollToIndex({
                index,
                animated: false,
                viewPosition: 0.5,
              });
            }, 100);
          }
        }
      }
      isInitialMount.current = false;
    }
  }, [threadId, messages, getScrollPosition]);

  // Handle start reached (scroll to top = load older)
  const handleStartReached = useCallback(async () => {
    if (!isLoadingOlder && hasMoreOlder) {
      await onLoadOlder();
    }
  }, [isLoadingOlder, hasMoreOlder, onLoadOlder]);

  // Handle scroll for position tracking
  const handleScroll = useCallback(
    (event: { nativeEvent: { contentOffset: { y: number } } }) => {
      const offset = event.nativeEvent.contentOffset.y;

      // Find the message closest to current view
      // This is approximate since we don't have exact positions
      const approximateIndex = Math.floor(offset / APPROXIMATE_ITEM_SIZE);
      const messageId = messages[approximateIndex]?.id;

      const position = { offset, messageId };

      // Save to store
      setScrollPosition(threadId, position);

      // Notify parent
      onScrollPositionChange?.(position);
    },
    [threadId, messages, setScrollPosition, onScrollPositionChange]
  );

  // Render message item - use existing component interfaces
  // Wrapped with MessageContextMenu for long-press fork capability
  const renderItem = useCallback(
    ({ item, index }: ListRenderItemInfo<Message>) => {
      // Check if this is an LLM message using speakerType or senderId
      const isLLM =
        item.senderId === 'llm' ||
        ['LLM_PRIMARY', 'LLM_PROVOKER'].includes(item.speakerType || '');

      // Check if this is the active streaming message (last message when streaming)
      const isActiveStream =
        (isThinking || isStreaming) &&
        index === messages.length - 1 &&
        isLLM;

      const messageContent = isLLM ? (
        <LLMMessageBubble
          content={isActiveStream && isStreaming ? undefined : item.content}
          partialContent={isActiveStream ? partialResponse : undefined}
          createdAt={item.createdAt}
          isThinking={isActiveStream && isThinking}
          isStreaming={isActiveStream && isStreaming}
          speakerType={
            isActiveStream && streamSpeakerType
              ? streamSpeakerType
              : (item.speakerType?.toLowerCase() as 'llm_primary' | 'llm_provoker' | undefined)
          }
          interjectionType={isActiveStream ? streamInterjectionType : undefined}
          onStopPress={isActiveStream ? cancel : undefined}
        />
      ) : (
        // MessageBubble expects a message prop with the full Message object
        <MessageBubble message={item} />
      );

      // Wrap all messages with context menu for fork capability
      return (
        <MessageContextMenu
          messageId={item.id}
          messageContent={item.content}
          threadId={threadId}
          roomId={roomId}
        >
          {messageContent}
        </MessageContextMenu>
      );
    },
    [
      threadId,
      roomId,
      messages.length,
      isThinking,
      isStreaming,
      partialResponse,
      streamSpeakerType,
      streamInterjectionType,
      cancel,
    ]
  );

  // Render thinking bubble when LLM is thinking but no message yet
  // (e.g., when last message is from human and LLM started thinking)
  const ListFooterComponent = useCallback(() => {
    // Show thinking bubble if LLM is active and last message isn't an LLM message
    const lastMessage = messages[messages.length - 1];
    const lastIsHuman =
      !lastMessage ||
      (lastMessage.senderId !== 'llm' &&
        !['LLM_PRIMARY', 'LLM_PROVOKER'].includes(lastMessage.speakerType || ''));

    if ((isThinking || isStreaming) && lastIsHuman) {
      return (
        <LLMMessageBubble
          content={undefined}
          partialContent={partialResponse}
          isThinking={isThinking}
          isStreaming={isStreaming}
          speakerType={streamSpeakerType}
          interjectionType={streamInterjectionType}
          onStopPress={cancel}
        />
      );
    }

    return null;
  }, [
    messages,
    isThinking,
    isStreaming,
    partialResponse,
    streamSpeakerType,
    streamInterjectionType,
    cancel,
  ]);

  // Header component (loading indicator for older messages)
  const ListHeaderComponent = useCallback(() => {
    if (isLoadingOlder) {
      return (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="small" color="#6366f1" />
          <Text style={styles.loadingText}>Loading older messages...</Text>
        </View>
      );
    }

    if (!hasMoreOlder && messages.length > 0) {
      return (
        <View style={styles.endContainer}>
          <Text style={styles.endText}>Beginning of conversation</Text>
        </View>
      );
    }

    return null;
  }, [isLoadingOlder, hasMoreOlder, messages.length]);

  // Empty state
  const ListEmptyComponent = useCallback(() => {
    if (isLoading) {
      return (
        <View style={styles.emptyContainer}>
          <ActivityIndicator size="large" color="#6366f1" />
        </View>
      );
    }

    return (
      <View style={styles.emptyContainer}>
        <Text style={styles.emptyText}>No messages yet</Text>
        <Text style={styles.emptySubtext}>Start the conversation!</Text>
      </View>
    );
  }, [isLoading]);

  // Key extractor
  const keyExtractor = useCallback((item: Message) => item.id, []);

  return (
    <FlashList
      ref={listRef}
      data={messages}
      renderItem={renderItem}
      keyExtractor={keyExtractor}
      // Bidirectional pagination support - FlashList v2 API
      maintainVisibleContentPosition={{
        autoscrollToTopThreshold: 10,
      }}
      // Load older messages when scrolling up
      onStartReached={handleStartReached}
      onStartReachedThreshold={LOAD_OLDER_THRESHOLD}
      // Scroll tracking
      onScroll={handleScroll}
      scrollEventThrottle={100}
      // Headers and empty state
      ListHeaderComponent={ListHeaderComponent}
      ListFooterComponent={ListFooterComponent}
      ListEmptyComponent={ListEmptyComponent}
      // Style
      contentContainerStyle={styles.contentContainer}
      showsVerticalScrollIndicator={true}
      // Performance
      drawDistance={500}
    />
  );
}

const styles = StyleSheet.create({
  contentContainer: {
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  loadingContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 16,
    gap: 8,
  },
  loadingText: {
    fontSize: 14,
    color: '#6b7280',
  },
  endContainer: {
    alignItems: 'center',
    paddingVertical: 16,
  },
  endText: {
    fontSize: 14,
    color: '#9ca3af',
  },
  emptyContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 48,
  },
  emptyText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#6b7280',
    marginBottom: 4,
  },
  emptySubtext: {
    fontSize: 14,
    color: '#9ca3af',
  },
});
