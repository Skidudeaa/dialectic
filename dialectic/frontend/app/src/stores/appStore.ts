import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type {
  User,
  Room,
  Thread,
  Message,
  Memory,
  PresenceUser,
  ConversationDNA,
  ProtocolState,
  Commitment,
  TradingSnapshot,
} from '../types/index.ts'

interface AppState {
  // Auth
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  roomToken: string | null;
  isAuthenticated: boolean;

  // Room
  currentRoom: Room | null;
  currentThread: Thread | null;
  threads: Thread[];
  messages: Message[];
  memories: Memory[];

  // Presence
  onlineUsers: PresenceUser[];
  typingUsers: string[];

  // LLM state
  isLLMThinking: boolean;
  isLLMStreaming: boolean;
  streamingContent: string;

  // Protocol
  activeProtocol: ProtocolState | null;

  // Analytics
  roomDNA: ConversationDNA | null;

  // Commitments
  activeCommitments: Commitment[];
  surfacedCommitments: Commitment[];

  // Trading
  tradingConfig: TradingSnapshot | null;

  // Actions
  setUser: (user: User, accessToken: string, refreshToken?: string) => void;
  setRoom: (room: Room, token: string) => void;
  setThread: (thread: Thread) => void;
  setThreads: (threads: Thread[]) => void;
  addMessage: (message: Message) => void;
  setMessages: (messages: Message[]) => void;
  setMemories: (memories: Memory[]) => void;
  updateStreamingContent: (content: string) => void;
  setLLMState: (thinking: boolean, streaming: boolean) => void;
  setProtocol: (protocol: ProtocolState | null) => void;
  updateProtocolPhase: (phase: number) => void;
  setTypingUser: (userId: string, isTyping: boolean) => void;
  setOnlineUsers: (users: PresenceUser[]) => void;
  setRoomDNA: (dna: ConversationDNA | null) => void;
  addCommitment: (commitment: Commitment) => void;
  setSurfacedCommitments: (commitments: Commitment[]) => void;
  setActiveCommitments: (commitments: Commitment[]) => void;
  setTradingConfig: (config: TradingSnapshot | null) => void;
  logout: () => void;
  leaveRoom: () => void;
}

const initialRoomState = {
  currentRoom: null,
  currentThread: null,
  threads: [],
  messages: [],
  memories: [],
  onlineUsers: [],
  typingUsers: [],
  isLLMThinking: false,
  isLLMStreaming: false,
  streamingContent: '',
  activeProtocol: null,
  roomDNA: null,
  activeCommitments: [],
  surfacedCommitments: [],
  tradingConfig: null,
  roomToken: null,
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      // Initial state
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      ...initialRoomState,

      // Actions
      setUser: (user, accessToken, refreshToken) =>
        set({
          user,
          accessToken,
          refreshToken: refreshToken ?? null,
          isAuthenticated: true,
        }),

      setRoom: (room, token) =>
        set({
          currentRoom: room,
          roomToken: token,
          // Reset room-specific state
          currentThread: null,
          threads: [],
          messages: [],
          memories: [],
          onlineUsers: [],
          typingUsers: [],
          isLLMThinking: false,
          isLLMStreaming: false,
          streamingContent: '',
          activeProtocol: null,
          roomDNA: null,
          activeCommitments: [],
          surfacedCommitments: [],
          tradingConfig: null,
        }),

      setThread: (thread) => set({ currentThread: thread }),

      setThreads: (threads) => set({ threads }),

      addMessage: (message) =>
        set((state) => {
          // Deduplicate by ID
          if (state.messages.some((m) => m.id === message.id)) {
            return state;
          }
          return { messages: [...state.messages, message] };
        }),

      setMessages: (messages) => set({ messages }),

      setMemories: (memories) => set({ memories }),

      updateStreamingContent: (content) => set({ streamingContent: content }),

      setLLMState: (thinking, streaming) =>
        set({
          isLLMThinking: thinking,
          isLLMStreaming: streaming,
          ...((!thinking && !streaming) ? { streamingContent: '' } : {}),
        }),

      setProtocol: (protocol) => set({ activeProtocol: protocol }),

      updateProtocolPhase: (phase) =>
        set((state) => {
          if (!state.activeProtocol) return state;
          return {
            activeProtocol: { ...state.activeProtocol, current_phase: phase },
          };
        }),

      setTypingUser: (userId, isTyping) =>
        set((state) => {
          const filtered = state.typingUsers.filter((id) => id !== userId);
          return {
            typingUsers: isTyping ? [...filtered, userId] : filtered,
          };
        }),

      setOnlineUsers: (users) => set({ onlineUsers: users }),

      setRoomDNA: (dna) => set({ roomDNA: dna }),

      addCommitment: (commitment) =>
        set((state) => ({
          activeCommitments: [...state.activeCommitments, commitment],
        })),

      setSurfacedCommitments: (commitments) =>
        set({ surfacedCommitments: commitments }),

      setActiveCommitments: (commitments) =>
        set({ activeCommitments: commitments }),

      setTradingConfig: (config) => set({ tradingConfig: config }),

      logout: () =>
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
          ...initialRoomState,
        }),

      leaveRoom: () => set(initialRoomState),
    }),
    {
      name: 'dialectic-auth',
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        isAuthenticated: state.isAuthenticated,
      }),
    },
  ),
)
