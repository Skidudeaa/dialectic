/**
 * Dialectic for macOS
 *
 * ARCHITECTURE: Bootstrap app with platform service initialization and chat UI.
 * WHY: Bare workflow required for react-native-macos (no Expo support).
 * TRADEOFF: Separate entry point vs code sharing - needed for platform init.
 */

import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, SafeAreaView } from 'react-native';
import { initializePlatform } from './src/platform-init';
import { MenuBar } from './src/native/MenuBar';
import {
  ChatLayout,
  CollapsibleSidebar,
  KeyboardShortcutsProvider,
  DropZone,
  useWindowPersistence,
  PlatformMessageList,
  MessageListEmpty,
} from '@dialectic/app';

// Message type for display
interface Message {
  id: string;
  content: string;
  speaker_type: 'HUMAN' | 'LLM_PRIMARY' | 'LLM_PROVOKER';
  speaker_name?: string;
  created_at: string;
}

// Placeholder message bubble - replace with actual import from @dialectic/app
// when mobile components are extracted to shared package
function MessageBubble({ message }: { message: Message }) {
  const isLLM = message.speaker_type !== 'HUMAN';
  return (
    <View style={[messageBubbleStyles.container, isLLM && messageBubbleStyles.llmContainer]}>
      <Text style={messageBubbleStyles.speaker}>
        {message.speaker_name || (isLLM ? 'Claude' : 'You')}
      </Text>
      <Text style={messageBubbleStyles.content}>{message.content}</Text>
    </View>
  );
}

const messageBubbleStyles = StyleSheet.create({
  container: {
    padding: 12,
    marginVertical: 4,
    marginHorizontal: 16,
    borderRadius: 12, // macOS uses rounded corners
    backgroundColor: '#e2e8f0',
    maxWidth: '80%',
    alignSelf: 'flex-end',
  },
  llmContainer: {
    backgroundColor: '#eef2ff', // Indigo-50 for Claude
    alignSelf: 'flex-start',
  },
  speaker: {
    fontSize: 12,
    fontWeight: '600',
    color: '#64748b',
    marginBottom: 4,
  },
  content: {
    fontSize: 14,
    color: '#1e293b',
    lineHeight: 20,
  },
});

export default function App() {
  const [initialized, setInitialized] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);

  // Initialize platform services
  useEffect(() => {
    initializePlatform();
    setInitialized(true);

    // TODO: Load actual messages from WebSocket/API
    // For now, show placeholder
    setMessages([
      {
        id: '1',
        content: 'Welcome to Dialectic for macOS!',
        speaker_type: 'LLM_PRIMARY',
        speaker_name: 'Claude',
        created_at: new Date().toISOString(),
      },
      {
        id: '2',
        content: 'This is a placeholder. Connect to a room to start chatting.',
        speaker_type: 'LLM_PRIMARY',
        speaker_name: 'Claude',
        created_at: new Date().toISOString(),
      },
    ]);
  }, []);

  // Persist window size/position
  useWindowPersistence();

  // Keyboard shortcuts (Cmd key on macOS)
  const shortcuts = [
    { key: 'n', withModifier: true, onPress: () => console.log('New room'), description: 'New room' },
    { key: 'f', withModifier: true, onPress: () => console.log('Search'), description: 'Search' },
    { key: ',', withModifier: true, onPress: () => console.log('Preferences'), description: 'Preferences' },
  ];

  const renderMessage = useCallback(({ item }: { item: Message }) => (
    <MessageBubble message={item} />
  ), []);

  const keyExtractor = useCallback((item: Message) => item.id, []);

  if (!initialized) {
    return (
      <View style={styles.container}>
        <Text style={styles.loadingText}>Loading...</Text>
      </View>
    );
  }

  return (
    <KeyboardShortcutsProvider shortcuts={shortcuts}>
      <SafeAreaView style={styles.container}>
        {/* Menu bar with dock integration */}
        <MenuBar
          unreadCount={0}
          onNewRoom={() => console.log('New room')}
          onSearch={() => console.log('Search')}
          onPreferences={() => console.log('Preferences')}
          onQuit={() => console.log('Quit')}
        />

        {/* Main layout with collapsible sidebar */}
        <DropZone onDrop={(files) => console.log('Files dropped:', files)}>
          <CollapsibleSidebar
            sidebar={
              <View style={styles.sidebar}>
                <Text style={styles.sidebarTitle}>Rooms</Text>
                <Text style={styles.sidebarItem}>General</Text>
                <Text style={styles.sidebarItem}>Random</Text>
              </View>
            }
          >
            <ChatLayout>
              <PlatformMessageList
                data={messages}
                renderItem={renderMessage}
                keyExtractor={keyExtractor}
                estimatedItemSize={80}
                ListEmptyComponent={<MessageListEmpty text="No messages yet. Join a room to start." />}
                inverted={false}
              />
            </ChatLayout>
          </CollapsibleSidebar>
        </DropZone>
      </SafeAreaView>
    </KeyboardShortcutsProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  loadingText: {
    fontSize: 16,
    color: '#999',
    textAlign: 'center',
    marginTop: 100,
  },
  sidebar: {
    padding: 16,
    backgroundColor: '#f9fafb',
  },
  sidebarTitle: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 12,
    color: '#1f2937',
  },
  sidebarItem: {
    fontSize: 14,
    paddingVertical: 8,
    color: '#374151',
  },
});
