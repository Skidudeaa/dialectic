import { create } from 'zustand';

interface TypingUser {
  userId: string;
  displayName: string;
  startedAt: number;
}

interface TypingState {
  // Users currently typing (keyed by userId)
  typingUsers: Record<string, TypingUser>;

  // Actions
  setUserTyping: (userId: string, displayName: string) => void;
  clearUserTyping: (userId: string) => void;
  clearAllTyping: () => void;
}

/**
 * ARCHITECTURE: In-memory store for typing indicators.
 * WHY: Typing state is ephemeral, no persistence needed.
 * TRADEOFF: Lost on remount, but that's fine for typing status.
 */
export const useTypingStore = create<TypingState>()((set) => ({
  typingUsers: {},

  setUserTyping: (userId, displayName) => {
    set((state) => ({
      typingUsers: {
        ...state.typingUsers,
        [userId]: {
          userId,
          displayName,
          startedAt: Date.now(),
        },
      },
    }));
  },

  clearUserTyping: (userId) => {
    set((state) => {
      const { [userId]: _, ...rest } = state.typingUsers;
      return { typingUsers: rest };
    });
  },

  clearAllTyping: () => set({ typingUsers: {} }),
}));
