/**
 * ARCHITECTURE: Zustand store for search state.
 * WHY: Centralized search state for overlay and navigation.
 * TRADEOFF: Additional store vs local state, but enables cross-component coordination.
 */

import { create } from 'zustand';

export interface SearchResult {
  id: string;
  threadId: string;
  content: string;
  snippet: string;
  senderName: string;
  speakerType: string;
  createdAt: string;
  score: number;
  source: 'local' | 'server';
}

export interface SearchFilters {
  dateFrom?: string;
  dateTo?: string;
  senderType?: 'human' | 'llm';
}

interface SearchState {
  isOpen: boolean;
  query: string;
  filters: SearchFilters;
  scope: 'current' | 'all';
  results: SearchResult[];
  isSearching: boolean;

  // Actions
  openSearch: () => void;
  closeSearch: () => void;
  setQuery: (query: string) => void;
  setFilters: (filters: SearchFilters) => void;
  setScope: (scope: 'current' | 'all') => void;
  setResults: (results: SearchResult[]) => void;
  setIsSearching: (isSearching: boolean) => void;
  reset: () => void;
}

export const useSearchStore = create<SearchState>()((set) => ({
  isOpen: false,
  query: '',
  filters: {},
  scope: 'current',
  results: [],
  isSearching: false,

  openSearch: () => set({ isOpen: true }),
  closeSearch: () => set({ isOpen: false, query: '', results: [] }),
  setQuery: (query) => set({ query }),
  setFilters: (filters) => set({ filters }),
  setScope: (scope) => set({ scope }),
  setResults: (results) => set({ results }),
  setIsSearching: (isSearching) => set({ isSearching }),
  reset: () =>
    set({
      query: '',
      filters: {},
      scope: 'current',
      results: [],
      isSearching: false,
    }),
}));
