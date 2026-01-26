/**
 * ARCHITECTURE: Full-screen search overlay with filters and results.
 * WHY: Focused search experience without leaving conversation context.
 * TRADEOFF: Overlay vs separate screen, but keeps conversation visible underneath.
 */

import React, { useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  TouchableOpacity,
  FlatList,
  SafeAreaView,
  ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { HighlightedText } from '@/components/ui/highlighted-text';
import { useSearch } from '@/hooks/use-search';
import { useSearchStore, type SearchResult } from '@/stores/search-store';

interface SearchOverlayProps {
  threadId: string;
  onResultPress: (result: SearchResult) => void;
  onClose: () => void;
}

export function SearchOverlay({
  threadId,
  onResultPress,
  onClose,
}: SearchOverlayProps) {
  const {
    query,
    setQuery,
    filters,
    setFilters,
    scope,
    setScope,
    results,
    isSearching,
    clear,
  } = useSearch({ threadId });

  const handleClose = useCallback(() => {
    clear();
    onClose();
  }, [clear, onClose]);

  const handleResultPress = useCallback(
    (result: SearchResult) => {
      onResultPress(result);
      handleClose();
    },
    [onResultPress, handleClose]
  );

  const renderResult = useCallback(
    ({ item }: { item: SearchResult }) => (
      <TouchableOpacity
        style={styles.resultItem}
        onPress={() => handleResultPress(item)}
        activeOpacity={0.7}
      >
        <View style={styles.resultHeader}>
          <Text style={styles.resultSender}>{item.senderName}</Text>
          <Text style={styles.resultDate}>
            {new Date(item.createdAt).toLocaleDateString()}
          </Text>
        </View>
        <HighlightedText text={item.snippet} style={styles.resultSnippet} />
        {item.source === 'local' && (
          <View style={styles.sourceTag}>
            <Text style={styles.sourceTagText}>Cached</Text>
          </View>
        )}
      </TouchableOpacity>
    ),
    [handleResultPress]
  );

  const keyExtractor = useCallback((item: SearchResult) => item.id, []);

  return (
    <SafeAreaView style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity onPress={handleClose} style={styles.closeButton}>
          <Ionicons name="close" size={24} color="#374151" />
        </TouchableOpacity>
        <View style={styles.searchInputContainer}>
          <Ionicons
            name="search"
            size={20}
            color="#9ca3af"
            style={styles.searchIcon}
          />
          <TextInput
            style={styles.searchInput}
            placeholder="Search messages..."
            placeholderTextColor="#9ca3af"
            value={query}
            onChangeText={setQuery}
            autoFocus
            returnKeyType="search"
          />
          {isSearching && (
            <ActivityIndicator size="small" color="#6366f1" />
          )}
        </View>
      </View>

      {/* Scope toggle */}
      <View style={styles.scopeContainer}>
        <TouchableOpacity
          style={[
            styles.scopeButton,
            scope === 'current' && styles.scopeButtonActive,
          ]}
          onPress={() => setScope('current')}
        >
          <Text
            style={[
              styles.scopeButtonText,
              scope === 'current' && styles.scopeButtonTextActive,
            ]}
          >
            This conversation
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[
            styles.scopeButton,
            scope === 'all' && styles.scopeButtonActive,
          ]}
          onPress={() => setScope('all')}
        >
          <Text
            style={[
              styles.scopeButtonText,
              scope === 'all' && styles.scopeButtonTextActive,
            ]}
          >
            All conversations
          </Text>
        </TouchableOpacity>
      </View>

      {/* Filters */}
      <View style={styles.filtersContainer}>
        <TouchableOpacity
          style={[
            styles.filterChip,
            filters.senderType === 'human' && styles.filterChipActive,
          ]}
          onPress={() =>
            setFilters({
              ...filters,
              senderType: filters.senderType === 'human' ? undefined : 'human',
            })
          }
        >
          <Text
            style={[
              styles.filterChipText,
              filters.senderType === 'human' && styles.filterChipTextActive,
            ]}
          >
            Human only
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[
            styles.filterChip,
            filters.senderType === 'llm' && styles.filterChipActive,
          ]}
          onPress={() =>
            setFilters({
              ...filters,
              senderType: filters.senderType === 'llm' ? undefined : 'llm',
            })
          }
        >
          <Text
            style={[
              styles.filterChipText,
              filters.senderType === 'llm' && styles.filterChipTextActive,
            ]}
          >
            Claude only
          </Text>
        </TouchableOpacity>
      </View>

      {/* Results */}
      <FlatList
        data={results}
        renderItem={renderResult}
        keyExtractor={keyExtractor}
        style={styles.resultsList}
        contentContainerStyle={styles.resultsContent}
        ListEmptyComponent={
          query.trim() ? (
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>
                {isSearching ? 'Searching...' : 'No results found'}
              </Text>
            </View>
          ) : (
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>
                Start typing to search messages
              </Text>
            </View>
          )
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
  },
  closeButton: {
    padding: 8,
  },
  searchInputContainer: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f3f4f6',
    borderRadius: 8,
    paddingHorizontal: 12,
    marginLeft: 8,
  },
  searchIcon: {
    marginRight: 8,
  },
  searchInput: {
    flex: 1,
    fontSize: 16,
    paddingVertical: 10,
    color: '#1f2937',
  },
  scopeContainer: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    paddingVertical: 8,
    gap: 8,
  },
  scopeButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: '#f3f4f6',
  },
  scopeButtonActive: {
    backgroundColor: '#6366f1',
  },
  scopeButtonText: {
    fontSize: 14,
    color: '#6b7280',
  },
  scopeButtonTextActive: {
    color: '#fff',
    fontWeight: '600',
  },
  filtersContainer: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    paddingBottom: 8,
    gap: 8,
  },
  filterChip: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  filterChipActive: {
    backgroundColor: '#ede9fe',
    borderColor: '#6366f1',
  },
  filterChipText: {
    fontSize: 12,
    color: '#6b7280',
  },
  filterChipTextActive: {
    color: '#6366f1',
    fontWeight: '600',
  },
  resultsList: {
    flex: 1,
  },
  resultsContent: {
    paddingHorizontal: 12,
  },
  resultItem: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  resultHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  resultSender: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1f2937',
  },
  resultDate: {
    fontSize: 12,
    color: '#9ca3af',
  },
  resultSnippet: {
    fontSize: 14,
    color: '#4b5563',
    lineHeight: 20,
  },
  sourceTag: {
    alignSelf: 'flex-start',
    marginTop: 4,
    paddingHorizontal: 6,
    paddingVertical: 2,
    backgroundColor: '#f3f4f6',
    borderRadius: 4,
  },
  sourceTagText: {
    fontSize: 10,
    color: '#9ca3af',
  },
  emptyContainer: {
    paddingVertical: 48,
    alignItems: 'center',
  },
  emptyText: {
    fontSize: 16,
    color: '#9ca3af',
  },
});
