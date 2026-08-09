import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { revokeAttachmentUrls } from '../lib/attachments.ts'
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
  LLMToolActivity,
  Attachment,
  PendingAttachmentBind,
} from '../types/index.ts'

/**
 * How long a send waits for its own message_created echo before its pending
 * bind is abandoned. Generous — the echo is a round trip, not a render — but
 * finite, so a dropped socket cannot strand entries in the queue forever.
 */
const PENDING_BIND_TTL_MS = 60_000

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
  /**
   * Attachments keyed by message id.
   *
   * Filled from two directions: optimistically for your own sends, at the
   * moment the message id becomes known, and — once the backend exposes a read
   * path — in bulk for the whole thread (see setAllAttachments).
   */
  attachments: Record<string, Attachment[]>;
  /** Uploads whose message id is not known yet. See PendingAttachmentBind. */
  pendingAttachmentBinds: PendingAttachmentBind[];

  // Presence
  onlineUsers: PresenceUser[];
  typingUsers: string[];

  // LLM state
  isLLMThinking: boolean;
  isLLMStreaming: boolean;
  streamingContent: string;
  /**
   * Tools the LLM is using right now, keyed by thread. Transient: it exists to
   * say "checking live prices" while the room waits, and is cleared the moment
   * the turn ends. The durable record is the finished message's own trace.
   */
  llmToolActivity: Record<string, LLMToolActivity[]>;

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
  setMessageAttachments: (messageId: string, attachments: Attachment[]) => void;
  /** Bulk fill, for a thread-wide read of attachments. */
  setAllAttachments: (byMessageId: Record<string, Attachment[]>) => void;
  queueAttachmentBind: (bind: Omit<PendingAttachmentBind, 'queuedAt'>) => void;
  /**
   * Claim the queued upload set belonging to a just-created message and file it
   * under that id. Returns the attachments still needing a server-side bind
   * (empty when this message carried none).
   */
  resolveAttachmentBind: (messageId: string, threadId: string, content: string) => Attachment[];
  setMemories: (memories: Memory[]) => void;
  updateStreamingContent: (content: string) => void;
  appendStreamingToken: (token: string) => void;
  setLLMState: (thinking: boolean, streaming: boolean) => void;
  recordToolActivity: (threadId: string, activity: LLMToolActivity) => void;
  clearToolActivity: (threadId: string) => void;
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
  attachments: {},
  pendingAttachmentBinds: [],
  onlineUsers: [],
  typingUsers: [],
  isLLMThinking: false,
  isLLMStreaming: false,
  streamingContent: '',
  llmToolActivity: {},
  activeProtocol: null,
  roomDNA: null,
  activeCommitments: [],
  surfacedCommitments: [],
  tradingConfig: null,
  roomToken: null,
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
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

      setRoom: (room, token) => {
        // Attachment bytes are cached as blob: URLs keyed by attachment id, and
        // every one of them belongs to the room being left. Revoking here is
        // what keeps a long session from holding every image it has ever
        // displayed in memory.
        revokeAttachmentUrls()
        set({
          currentRoom: room,
          roomToken: token,
          // Reset room-specific state
          currentThread: null,
          threads: [],
          messages: [],
          memories: [],
          reactions: {},
          attachments: {},
          pendingAttachmentBinds: [],
          onlineUsers: [],
          typingUsers: [],
          isLLMThinking: false,
          isLLMStreaming: false,
          streamingContent: '',
          llmToolActivity: {},
          activeProtocol: null,
          roomDNA: null,
          activeCommitments: [],
          surfacedCommitments: [],
          tradingConfig: null,
        })
      },

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

      setMessageAttachments: (messageId, attachments) =>
        set((state) => ({
          attachments: { ...state.attachments, [messageId]: attachments },
        })),

      // Merge rather than replace: a bulk read must not drop the optimistic
      // entries for sends the server has not projected back yet.
      setAllAttachments: (byMessageId) =>
        set((state) => ({ attachments: { ...state.attachments, ...byMessageId } })),

      queueAttachmentBind: (bind) =>
        set((state) => ({
          pendingAttachmentBinds: [
            ...state.pendingAttachmentBinds.filter(
              (entry) => Date.now() - entry.queuedAt < PENDING_BIND_TTL_MS,
            ),
            { ...bind, queuedAt: Date.now() },
          ],
        })),

      // WHY match on (thread, content) instead of an id the client chose: the
      // message id is minted server-side, and send_message carries no
      // correlation token, so the echo is the first moment the two can be
      // joined. FIFO on ties, so sending the same text twice binds the first
      // upload set to the first message.
      resolveAttachmentBind: (messageId, threadId, content) => {
        const queue = get().pendingAttachmentBinds
        const index = queue.findIndex(
          (entry) => entry.threadId === threadId && entry.content === content,
        )
        if (index === -1) return []
        const claimed = queue[index]
        set((state) => ({
          pendingAttachmentBinds: state.pendingAttachmentBinds.filter((_, i) => i !== index),
          attachments: { ...state.attachments, [messageId]: claimed.attachments },
        }))
        return claimed.attachments
      },

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

      // A finished/failed event updates the entry its start created, matched on
      // tool name — the loop never runs the same tool twice concurrently, and
      // matching on name keeps this a one-line update instead of an id scheme
      // the server would then have to carry.
      recordToolActivity: (threadId, activity) =>
        set((state) => {
          const current = state.llmToolActivity[threadId] ?? []
          let next: LLMToolActivity[]
          if (activity.status === 'started') {
            next = [...current, activity]
          } else {
            const index = current.map((a) => a.tool).lastIndexOf(activity.tool)
            next = index === -1
              ? [...current, activity]
              : current.map((a, i) => (i === index ? { ...a, ...activity } : a))
          }
          return { llmToolActivity: { ...state.llmToolActivity, [threadId]: next } }
        }),

      clearToolActivity: (threadId) =>
        set((state) => {
          if (!(threadId in state.llmToolActivity)) return state
          const next = { ...state.llmToolActivity }
          delete next[threadId]
          return { llmToolActivity: next }
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

      logout: (reason) => {
        revokeAttachmentUrls()
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
          signedOutReason: reason ?? null,
          ...initialRoomState,
        })
      },

      leaveRoom: () => {
        revokeAttachmentUrls()
        set(initialRoomState)
      },
    }),
    {
      name: 'dialectic-auth',
      // WHY currentRoom/roomToken persist: phones evict background tabs
      // constantly — without these, every app switch dumps the user back on
      // the room list. The rehydrated token is validated on mount; a revoked
      // one falls back to the room list (see ChatLayout).
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        isAuthenticated: state.isAuthenticated,
        currentRoom: state.currentRoom,
        roomToken: state.roomToken,
      }),
    },
  ),
)
