/**
 * ARCHITECTURE: Zustand store for LLM streaming state management.
 * WHY: LLM responses stream token-by-token; UI needs reactive partial updates.
 * TRADEOFF: Single-thread state simpler than per-thread Map for v1.
 */

import { create } from 'zustand';
import { websocketService } from '@/services/websocket';

interface LLMState {
  // State flags
  isThinking: boolean; // Claude processing, before streaming starts
  isStreaming: boolean; // Tokens actively arriving
  partialResponse: string; // Accumulated content during streaming

  // Tracking
  streamingMessageId: string | null; // Message ID once streaming begins
  activeThreadId: string | null; // Thread where LLM is active

  // Interjection metadata (populated on llm_done)
  speakerType: 'llm_primary' | 'llm_provoker' | null;
  interjectionType: 'summoned' | 'proactive' | null;
  interjectionReason: string | null;

  // Actions
  startThinking: (threadId: string) => void;
  startStreaming: (messageId: string) => void;
  appendToken: (token: string) => void;
  finishStreaming: (metadata?: {
    speakerType: 'llm_primary' | 'llm_provoker';
    interjectionType: 'summoned' | 'proactive';
    interjectionReason?: string;
  }) => void;
  cancelResponse: () => void;
  cancelStream: (threadId: string) => void; // Sends cancel to server + clears state
  reset: () => void;
}

const initialState = {
  isThinking: false,
  isStreaming: false,
  partialResponse: '',
  streamingMessageId: null,
  activeThreadId: null,
  speakerType: null,
  interjectionType: null,
  interjectionReason: null,
};

export const useLLMStore = create<LLMState>()((set, get) => ({
  ...initialState,

  startThinking: (threadId) =>
    set({
      isThinking: true,
      isStreaming: false,
      partialResponse: '',
      streamingMessageId: null,
      activeThreadId: threadId,
      speakerType: null,
      interjectionType: null,
      interjectionReason: null,
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

  finishStreaming: (metadata) =>
    set({
      isThinking: false,
      isStreaming: false,
      partialResponse: '',
      streamingMessageId: null,
      activeThreadId: null,
      speakerType: metadata?.speakerType ?? null,
      interjectionType: metadata?.interjectionType ?? null,
      interjectionReason: metadata?.interjectionReason ?? null,
    }),

  cancelResponse: () => set(initialState),

  cancelStream: (threadId) => {
    const { activeThreadId } = get();
    // Only cancel if this is the active thread
    if (activeThreadId === threadId) {
      // Send cancel to server
      websocketService.send({
        type: 'cancel_llm',
        payload: { thread_id: threadId },
      });

      // Clear local state immediately for responsive UI
      set(initialState);
    }
  },

  reset: () => set(initialState),
}));
