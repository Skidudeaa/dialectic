/**
 * ARCHITECTURE: MMKV-backed store for session continuity.
 * WHY: Remember user's position across app restarts (fast, synchronous access).
 * TRADEOFF: State duplication vs server, but enables instant restore.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { createMMKV, type MMKV } from 'react-native-mmkv';

// Separate MMKV instance for session data
const storage: MMKV = createMMKV({ id: 'session-storage' });

export interface ScrollPosition {
  offset: number;
  messageId?: string; // For jump-to-message after pagination
}

interface SessionState {
  // Last active conversation
  lastRoomId: string | null;
  lastThreadId: string | null;

  // Scroll positions per thread (threadId -> position)
  scrollPositions: Record<string, ScrollPosition>;

  // Drafts per thread (threadId -> content)
  drafts: Record<string, string>;

  // Actions
  setLastConversation: (roomId: string, threadId: string) => void;
  clearLastConversation: () => void;
  setScrollPosition: (threadId: string, position: ScrollPosition) => void;
  getScrollPosition: (threadId: string) => ScrollPosition | undefined;
  setDraft: (threadId: string, content: string) => void;
  getDraft: (threadId: string) => string | undefined;
  clearDraft: (threadId: string) => void;
  clearAllDrafts: () => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set, get) => ({
      lastRoomId: null,
      lastThreadId: null,
      scrollPositions: {},
      drafts: {},

      setLastConversation: (roomId, threadId) =>
        set({ lastRoomId: roomId, lastThreadId: threadId }),

      clearLastConversation: () =>
        set({ lastRoomId: null, lastThreadId: null }),

      setScrollPosition: (threadId, position) =>
        set((state) => ({
          scrollPositions: {
            ...state.scrollPositions,
            [threadId]: position,
          },
        })),

      getScrollPosition: (threadId) => get().scrollPositions[threadId],

      setDraft: (threadId, content) =>
        set((state) => ({
          drafts: {
            ...state.drafts,
            [threadId]: content,
          },
        })),

      getDraft: (threadId) => get().drafts[threadId],

      clearDraft: (threadId) =>
        set((state) => {
          const { [threadId]: _, ...rest } = state.drafts;
          return { drafts: rest };
        }),

      clearAllDrafts: () => set({ drafts: {} }),
    }),
    {
      name: 'session-state',
      storage: createJSONStorage(() => ({
        setItem: (name, value) => storage.set(name, value),
        getItem: (name) => storage.getString(name) ?? null,
        removeItem: (name) => {
          storage.remove(name);
        },
      })),
      // Only persist these fields (exclude computed getters)
      partialize: (state) => ({
        lastRoomId: state.lastRoomId,
        lastThreadId: state.lastThreadId,
        scrollPositions: state.scrollPositions,
        drafts: state.drafts,
      }),
    }
  )
);
