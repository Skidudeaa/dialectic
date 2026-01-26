/**
 * Platform-aware message list component.
 *
 * ARCHITECTURE: Uses FlashList on mobile for performance, FlatList on desktop for compatibility.
 * WHY: FlashList requires native modules that may not work on react-native-macos/windows.
 * TRADEOFF: Desktop gets slightly less optimized list, but guaranteed compatibility.
 */

import React from 'react';
import { View, StyleSheet, ActivityIndicator, Text, FlatList, Platform } from 'react-native';

// Conditional import - FlashList only on mobile
let FlashListComponent: any = null;
if (Platform.OS === 'ios' || Platform.OS === 'android') {
  try {
    FlashListComponent = require('@shopify/flash-list').FlashList;
  } catch {
    // FlashList not available, will use FlatList
  }
}

const isDesktop = Platform.OS === 'macos' || Platform.OS === 'windows';

export interface PlatformMessageListProps<T> {
  data: T[];
  renderItem: (info: { item: T; index: number }) => React.ReactElement;
  keyExtractor: (item: T, index: number) => string;
  estimatedItemSize?: number;
  onEndReached?: () => void;
  onEndReachedThreshold?: number;
  ListHeaderComponent?: React.ComponentType | React.ReactElement | null;
  ListFooterComponent?: React.ComponentType | React.ReactElement | null;
  ListEmptyComponent?: React.ComponentType | React.ReactElement | null;
  inverted?: boolean;
  onScroll?: (event: any) => void;
  contentContainerStyle?: any;
  showsVerticalScrollIndicator?: boolean;
}

/**
 * Platform-aware message list component.
 *
 * Uses FlashList on mobile (iOS/Android) for performance.
 * Uses FlatList on desktop (macOS/Windows) for compatibility.
 */
export function PlatformMessageList<T>({
  data,
  renderItem,
  keyExtractor,
  estimatedItemSize = 80,
  onEndReached,
  onEndReachedThreshold = 0.3,
  ListHeaderComponent,
  ListFooterComponent,
  ListEmptyComponent,
  inverted = false,
  onScroll,
  contentContainerStyle,
  showsVerticalScrollIndicator = true,
}: PlatformMessageListProps<T>) {
  // Use FlashList on mobile if available, FlatList on desktop
  const useFlashList = !isDesktop && FlashListComponent;

  if (useFlashList) {
    return (
      <FlashListComponent
        data={data}
        renderItem={renderItem}
        keyExtractor={keyExtractor}
        estimatedItemSize={estimatedItemSize}
        onEndReached={onEndReached}
        onEndReachedThreshold={onEndReachedThreshold}
        ListHeaderComponent={ListHeaderComponent}
        ListFooterComponent={ListFooterComponent}
        ListEmptyComponent={ListEmptyComponent}
        inverted={inverted}
        onScroll={onScroll}
        contentContainerStyle={contentContainerStyle}
        showsVerticalScrollIndicator={showsVerticalScrollIndicator}
      />
    );
  }

  // Desktop fallback: FlatList
  return (
    <FlatList
      data={data}
      renderItem={renderItem}
      keyExtractor={keyExtractor}
      onEndReached={onEndReached}
      onEndReachedThreshold={onEndReachedThreshold}
      ListHeaderComponent={ListHeaderComponent}
      ListFooterComponent={ListFooterComponent}
      ListEmptyComponent={ListEmptyComponent}
      inverted={inverted}
      onScroll={onScroll}
      contentContainerStyle={contentContainerStyle}
      showsVerticalScrollIndicator={showsVerticalScrollIndicator}
      // Desktop-specific optimizations
      windowSize={10}
      maxToRenderPerBatch={10}
      updateCellsBatchingPeriod={50}
      removeClippedSubviews={Platform.OS !== 'windows'} // Can cause issues on Windows
    />
  );
}

/**
 * Loading indicator for message list.
 */
export function MessageListLoading() {
  return (
    <View style={styles.loadingContainer}>
      <ActivityIndicator size="small" color="#6366f1" />
    </View>
  );
}

/**
 * Empty state for message list.
 */
export function MessageListEmpty({ text = 'No messages yet' }: { text?: string }) {
  return (
    <View style={styles.emptyContainer}>
      <Text style={styles.emptyText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  loadingContainer: {
    padding: 16,
    alignItems: 'center',
  },
  emptyContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
  },
  emptyText: {
    fontSize: 14,
    color: '#64748b',
  },
});
