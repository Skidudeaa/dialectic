/**
 * ARCHITECTURE: Long-press context menu wrapper for messages.
 * WHY: Provides fork-from-here and copy functionality on any message.
 * TRADEOFF: HoldItem wrapping adds overhead but enables Telegram-style UX.
 */

import React, { useCallback } from 'react';
import { Alert, Platform } from 'react-native';
import { HoldItem } from 'react-native-hold-menu';
import * as Clipboard from 'expo-clipboard';
import { useForkThread } from '@/hooks/use-fork';

interface MessageContextMenuProps {
  children: React.ReactElement;
  messageId: string;
  messageContent: string;
  threadId: string;
  roomId: string;
}

/**
 * Wraps a message with long-press context menu functionality.
 * Provides "Fork from here" and "Copy" options.
 */
export function MessageContextMenu({
  children,
  messageId,
  messageContent,
  threadId,
  roomId,
}: MessageContextMenuProps) {
  const { forkThread, isForking } = useForkThread();

  const handleFork = useCallback(() => {
    // CONTEXT.md: Optional naming prompt - allow skip
    if (Platform.OS === 'ios') {
      Alert.prompt(
        'Name this branch',
        'Give your branch a name (optional)',
        [
          {
            text: 'Skip',
            style: 'cancel',
            onPress: () => {
              forkThread({
                roomId,
                sourceThreadId: threadId,
                forkAfterMessageId: messageId,
                // Auto-generate title from timestamp if skipped
                title: `Branch ${new Date().toLocaleDateString()}`,
              });
            },
          },
          {
            text: 'Create',
            onPress: (title?: string) => {
              forkThread({
                roomId,
                sourceThreadId: threadId,
                forkAfterMessageId: messageId,
                title: title || `Branch ${new Date().toLocaleDateString()}`,
              });
            },
          },
        ],
        'plain-text',
        ''
      );
    } else {
      // Android: Alert.prompt is not supported, fork directly with auto-generated title
      forkThread({
        roomId,
        sourceThreadId: threadId,
        forkAfterMessageId: messageId,
        title: `Branch ${new Date().toLocaleDateString()}`,
      });
    }
  }, [roomId, threadId, messageId, forkThread]);

  const handleCopy = useCallback(async () => {
    await Clipboard.setStringAsync(messageContent);
  }, [messageContent]);

  // Menu items for hold menu - using Ionicons icon names
  const menuItems = [
    {
      text: 'Fork from here',
      icon: 'git-branch-outline',
      onPress: handleFork,
      isDestructive: false,
    },
    {
      text: 'Copy',
      icon: 'copy-outline',
      onPress: handleCopy,
      isDestructive: false,
    },
  ];

  return (
    <HoldItem
      items={menuItems}
      hapticFeedback="Medium"
      activateOn="hold"
      menuAnchorPosition="bottom-center"
      closeOnTap
    >
      {children}
    </HoldItem>
  );
}
