/**
 * ARCHITECTURE: Combined local + server search hook with debouncing.
 * WHY: Local search is instant; server search extends to full history.
 * TRADEOFF: Complexity of merging sources vs single source, but best UX.
 */

import { useCallback, useEffect, useRef } from 'react';
import { api } from '@/services/api';
import { searchLocalMessages, type LocalSearchResult } from '@/services/history/search-service';
import { useSearchStore, type SearchResult, type SearchFilters } from '@/stores/search-store';

const SEARCH_DEBOUNCE_MS = 300;

interface UseSearchOptions {
  threadId: string;
}

interface UseSearchReturn {
  query: string;
  setQuery: (query: string) => void;
  filters: SearchFilters;
  setFilters: (filters: SearchFilters) => void;
  scope: 'current' | 'all';
  setScope: (scope: 'current' | 'all') => void;
  results: SearchResult[];
  isSearching: boolean;
  search: (query: string) => Promise<void>;
  clear: () => void;
}

/**
 * Hook for searching messages locally and on server.
 *
 * Local search runs immediately, server search follows with debounce.
 * Results are merged and deduplicated.
 *
 * @example
 * const { query, setQuery, results, isSearching } = useSearch({ threadId });
 */
export function useSearch({ threadId }: UseSearchOptions): UseSearchReturn {
  const {
    query,
    setQuery,
    filters,
    setFilters,
    scope,
    setScope,
    results,
    setResults,
    isSearching,
    setIsSearching,
    reset,
  } = useSearchStore();

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Perform the search
  const search = useCallback(
    async (searchQuery: string) => {
      if (!searchQuery.trim()) {
        setResults([]);
        return;
      }

      setIsSearching(true);

      try {
        // 1. Local search first (instant)
        const localResults = await searchLocalMessages(
          scope === 'current' ? threadId : null,
          searchQuery,
          filters
        );

        const localSearchResults: SearchResult[] = localResults.map((r) => ({
          ...r,
          source: 'local' as const,
        }));

        setResults(localSearchResults);

        // 2. Server search (for 'all' scope or to extend local results)
        abortRef.current?.abort();
        abortRef.current = new AbortController();

        const response = await api.get('/messages/search', {
          params: {
            q: searchQuery,
            thread_id: scope === 'current' ? threadId : undefined,
            date_from: filters.dateFrom,
            date_to: filters.dateTo,
            speaker_type: filters.senderType,
            limit: 50,
          },
          signal: abortRef.current.signal,
        });

        const serverResults: SearchResult[] = (response.data || []).map(
          (r: LocalSearchResult) => ({
            ...r,
            source: 'server' as const,
          })
        );

        // 3. Merge and deduplicate (local results first, then server)
        const seen = new Set<string>();
        const merged: SearchResult[] = [];

        for (const r of localSearchResults) {
          if (!seen.has(r.id)) {
            seen.add(r.id);
            merged.push(r);
          }
        }

        for (const r of serverResults) {
          if (!seen.has(r.id)) {
            seen.add(r.id);
            merged.push(r);
          }
        }

        // Sort by score descending
        merged.sort((a, b) => b.score - a.score);

        setResults(merged);
      } catch (error) {
        // Ignore abort errors
        if ((error as Error).name !== 'AbortError') {
          console.error('[useSearch] Search error:', error);
        }
      } finally {
        setIsSearching(false);
      }
    },
    [threadId, scope, filters, setResults, setIsSearching]
  );

  // Debounced search on query change
  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    if (!query.trim()) {
      setResults([]);
      return;
    }

    debounceRef.current = setTimeout(() => {
      search(query);
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [query, search, setResults]);

  // Re-search when filters or scope change
  useEffect(() => {
    if (query.trim()) {
      search(query);
    }
  }, [filters, scope]); // eslint-disable-line react-hooks/exhaustive-deps

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const clear = useCallback(() => {
    reset();
  }, [reset]);

  return {
    query,
    setQuery,
    filters,
    setFilters,
    scope,
    setScope,
    results,
    isSearching,
    search,
    clear,
  };
}
