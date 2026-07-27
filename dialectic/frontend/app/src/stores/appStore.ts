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
  Reaction,
} from '../types/index.ts'

interface AppState {
  // Auth
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  roomToken: string | null;
  isAuthenticated: boolean;
  // Why the session ended, when the server told us (e.g. signed in on another
  // device). Deliberately NOT persisted: it explains the sign-out that just
  // happened, and should not greet the user again after a manual reload.
  signedOutReason: string | null;

  // Room
  currentRoom: Room | null;
  currentThread: Thread | null;
  threads: Thread[];
  messages: Message[];
  memories: Memory[];
  /** Reactions keyed by message id. Absent means none. */
  reactions: Record<string, Reaction[]>;

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
  editMessage: (messageId: string, content: string, editedAt: string) => void;
  removeMessage: (messageId: string) => void;
  setMessageReactions: (messageId: string, reactions: Reaction[]) => void;
  setAllReactions: (byMessageId: Record<string, Reaction[]>) => void;
  setMemories: (memories: Memory[]) => void;
  updateStreamingContent: (content: string) => void;
  appendStreamingToken: (token: string) => void;
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
  logout: (reason?: string) => void;
  leaveRoom: () => void;
}

const initialRoomState = {
  currentRoom: null,
  currentThread: null,
  threads: [],
  messages: [],
  memories: [],
  reactions: {},
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
      signedOutReason: null,
      ...initialRoomState,

      // Actions
      setUser: (user, accessToken, refreshToken) =>
        set({
          user,
          accessToken,
          refreshToken: refreshToken ?? null,
          isAuthenticated: true,
          signedOutReason: null,
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
          reactions: {},
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

      editMessage: (messageId, content, editedAt) =>
        set((state) => ({
          messages: state.messages.map((m) =>
            m.id === messageId ? { ...m, content, edited_at: editedAt } : m,
          ),
        })),

      // Deletion is soft on the server, but the message is gone from every read
      // path — so dropping it here matches what a reload would show.
      removeMessage: (messageId) =>
        set((state) => ({
          messages: state.messages.filter((m) => m.id !== messageId),
        })),

      setMessageReactions: (messageId, reactions) =>
        set((state) => {
          const next = { ...state.reactions }
          if (reactions.length === 0) delete next[messageId]
          else next[messageId] = reactions
          return { reactions: next }
        }),

      setAllReactions: (byMessageId) => set({ reactions: byMessageId }),

      setMemories: (memories) => set({ memories }),

      updateStreamingContent: (content) => set({ streamingContent: content }),

      // WHY: The server streams one token per llm_streaming event
      // ({token, index}), not accumulated content — the client owns
      // accumulation.
      appendStreamingToken: (token) =>
        set((state) => ({ streamingContent: state.streamingContent + token })),

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

      logout: (reason) =>
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
          signedOutReason: reason ?? null,
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
