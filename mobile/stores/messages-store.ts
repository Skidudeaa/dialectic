/**
 * ARCHITECTURE: Normalized message store with delivery tracking.
 * WHY: Optimistic updates require matching client ID to server ID.
 * TRADEOFF: More complex state shape vs reliable message deduplication.
 */

import { create } from 'zustand';

export type DeliveryStatus = 'sending' | 'sent' | 'delivered' | 'read' | 'failed';

export interface Message {
  id: string;
  clientId?: string; // For matching optimistic updates
  threadId: string;
  content: string;
  senderId: string;
  senderName?: string;
  createdAt: string;
  deliveryStatus: DeliveryStatus;
  readBy: string[]; // User IDs who have read
  sequence?: number;
  isMine: boolean;
}

interface MessagesState {
  // Messages keyed by ID (server ID or client ID for pending)
  messages: Record<string, Message>;
  // Thread ID -> array of message IDs (for ordering)
  threadMessages: Record<string, string[]>;
  // Current user ID (for isMine determination)
  currentUserId: string | null;

  // Actions
  setCurrentUserId: (userId: string) => void;
  addOptimistic: (
    clientId: string,
    message: Omit<Message, 'id' | 'deliveryStatus' | 'readBy' | 'isMine'>
  ) => void;
  confirmSent: (clientId: string, serverId: string, sequence: number) => void;
  addMessage: (message: Omit<Message, 'isMine'>) => void;
  markDelivered: (messageId: string) => void;
  markRead: (messageId: string, userId: string) => void;
  markFailed: (clientId: string) => void;
  retryFailed: (clientId: string) => void;
  clearThread: (threadId: string) => void;
}

export const useMessagesStore = create<MessagesState>()((set, get) => ({
  messages: {},
  threadMessages: {},
  currentUserId: null,

  setCurrentUserId: (userId) => set({ currentUserId: userId }),

  addOptimistic: (clientId, message) => {
    const { currentUserId } = get();
    set((state) => {
      const newMessage: Message = {
        ...message,
        id: clientId,
        clientId,
        deliveryStatus: 'sending',
        readBy: [],
        isMine: message.senderId === currentUserId,
      };

      const threadMsgs = state.threadMessages[message.threadId] || [];

      return {
        messages: {
          ...state.messages,
          [clientId]: newMessage,
        },
        threadMessages: {
          ...state.threadMessages,
          [message.threadId]: [...threadMsgs, clientId],
        },
      };
    });
  },

  confirmSent: (clientId, serverId, sequence) => {
    set((state) => {
      const optimistic = state.messages[clientId];
      if (!optimistic) return state;

      // Remove optimistic entry, add confirmed entry
      const { [clientId]: _, ...restMessages } = state.messages;

      // Update thread message list (replace clientId with serverId)
      const threadMsgs = state.threadMessages[optimistic.threadId] || [];
      const updatedThreadMsgs = threadMsgs.map((id) =>
        id === clientId ? serverId : id
      );

      return {
        messages: {
          ...restMessages,
          [serverId]: {
            ...optimistic,
            id: serverId,
            deliveryStatus: 'sent',
            sequence,
          },
        },
        threadMessages: {
          ...state.threadMessages,
          [optimistic.threadId]: updatedThreadMsgs,
        },
      };
    });
  },

  addMessage: (message) => {
    const { currentUserId, messages } = get();

    // Skip if we already have this message (deduplication)
    if (messages[message.id]) return;

    set((state) => {
      const newMessage: Message = {
        ...message,
        isMine: message.senderId === currentUserId,
      };

      const threadMsgs = state.threadMessages[message.threadId] || [];

      // Insert in sequence order
      const insertIndex = threadMsgs.findIndex((id) => {
        const msg = state.messages[id];
        return (
          msg && msg.sequence && message.sequence && msg.sequence > message.sequence
        );
      });

      const updatedThreadMsgs =
        insertIndex === -1
          ? [...threadMsgs, message.id]
          : [
              ...threadMsgs.slice(0, insertIndex),
              message.id,
              ...threadMsgs.slice(insertIndex),
            ];

      return {
        messages: {
          ...state.messages,
          [message.id]: newMessage,
        },
        threadMessages: {
          ...state.threadMessages,
          [message.threadId]: updatedThreadMsgs,
        },
      };
    });
  },

  markDelivered: (messageId) => {
    set((state) => {
      const msg = state.messages[messageId];
      if (!msg || msg.deliveryStatus === 'read') return state;

      return {
        messages: {
          ...state.messages,
          [messageId]: { ...msg, deliveryStatus: 'delivered' },
        },
      };
    });
  },

  markRead: (messageId, userId) => {
    set((state) => {
      const msg = state.messages[messageId];
      if (!msg) return state;

      const readBy = msg.readBy.includes(userId)
        ? msg.readBy
        : [...msg.readBy, userId];

      return {
        messages: {
          ...state.messages,
          [messageId]: {
            ...msg,
            deliveryStatus: 'read',
            readBy,
          },
        },
      };
    });
  },

  markFailed: (clientId) => {
    set((state) => {
      const msg = state.messages[clientId];
      if (!msg) return state;

      return {
        messages: {
          ...state.messages,
          [clientId]: { ...msg, deliveryStatus: 'failed' },
        },
      };
    });
  },

  retryFailed: (clientId) => {
    set((state) => {
      const msg = state.messages[clientId];
      if (!msg || msg.deliveryStatus !== 'failed') return state;

      return {
        messages: {
          ...state.messages,
          [clientId]: { ...msg, deliveryStatus: 'sending' },
        },
      };
    });
  },

  clearThread: (threadId) => {
    set((state) => {
      const msgIds = state.threadMessages[threadId] || [];
      const { [threadId]: _, ...restThreads } = state.threadMessages;

      const newMessages = { ...state.messages };
      msgIds.forEach((id) => delete newMessages[id]);

      return {
        messages: newMessages,
        threadMessages: restThreads,
      };
    });
  },
}));
