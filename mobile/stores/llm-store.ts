/**
 * ARCHITECTURE: Zustand store for LLM streaming state management.
 * WHY: LLM responses stream token-by-token; UI needs reactive partial updates.
 * TRADEOFF: Per-thread state would be cleaner but adds complexity for v1.
 */

import { create } from 'zustand';

interface LLMState {
  // State flags
  isThinking: boolean; // Claude processing, before streaming starts
  isStreaming: boolean; // Tokens actively arriving
  partialResponse: string; // Accumulated content during streaming

  // Tracking
  streamingMessageId: string | null; // Message ID once streaming begins
  activeThreadId: string | null; // Thread where LLM is active

  // Actions
  startThinking: (threadId: string) => void;
  startStreaming: (messageId: string) => void;
  appendToken: (token: string) => void;
  finishStreaming: () => void;
  cancelResponse: () => void;
  reset: () => void;
}

const initialState = {
  isThinking: false,
  isStreaming: false,
  partialResponse: '',
  streamingMessageId: null,
  activeThreadId: null,
};

export const useLLMStore = create<LLMState>()((set) => ({
  ...initialState,

  startThinking: (threadId) =>
    set({
      isThinking: true,
      isStreaming: false,
      partialResponse: '',
      streamingMessageId: null,
      activeThreadId: threadId,
    }),

  startStreaming: (messageId) =>
    set({
      isThinking: false,
      isStreaming: true,
      streamingMessageId: messageId,
    }),

  appendToken: (token) =>
    set((state) => ({
      partialResponse: state.partialResponse + token,
    })),

  finishStreaming: () =>
    set({
      isThinking: false,
      isStreaming: false,
      partialResponse: '',
      streamingMessageId: null,
      activeThreadId: null,
    }),

  cancelResponse: () => set(initialState),

  reset: () => set(initialState),
}));
