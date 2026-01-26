/**
 * ARCHITECTURE: Pagination hook coordinating cache and server.
 * WHY: Load from cache first (instant), then fetch from server for older messages.
 * TRADEOFF: Complexity of two sources vs single, but enables offline + full history.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { api } from '@/services/api';
import {
  cacheMessages,
  getCachedMessages,
  getCacheSequenceRange,
  type CacheableMessage,
} from '@/services/history/message-cache';
import type { Message } from '@/stores/messages-store';

interface PaginationState {
  hasMoreBefore: boolean;
  hasMoreAfter: boolean;
  oldestSequence: number | null;
  newestSequence: number | null;
}

interface UseMessageHistoryOptions {
  threadId: string;
  roomId: string;
  initialLimit?: number;
  pageSize?: number;
}

interface UseMessageHistoryReturn {
  messages: Message[];
  isLoading: boolean;
  isLoadingOlder: boolean;
  error: Error | null;
  hasMoreOlder: boolean;
  loadOlder: () => Promise<void>;
  refresh: () => Promise<void>;
}

/**
 * Hook for loading message history with pagination.
 *
 * Loads from local cache first, then fetches from server.
 * Supports upward pagination for older messages.
 *
 * @example
 * const {
 *   messages,
 *   isLoading,
 *   isLoadingOlder,
 *   hasMoreOlder,
 *   loadOlder,
 * } = useMessageHistory({ threadId, roomId });
 */
export function useMessageHistory({
  threadId,
  roomId,
  initialLimit = 50,
  pageSize = 30,
}: UseMessageHistoryOptions): UseMessageHistoryReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [pagination, setPagination] = useState<PaginationState>({
    hasMoreBefore: true,
    hasMoreAfter: false,
    oldestSequence: null,
    newestSequence: null,
  });

  // Prevent concurrent loads
  const loadingRef = useRef(false);

  // Convert API/cache message to store Message format
  const toMessage = useCallback(
    (msg: CacheableMessage, currentUserId?: string): Message => ({
      id: msg.id,
      threadId: msg.threadId,
      content: msg.content,
      senderId: msg.senderId,
      senderName: msg.senderName,
      createdAt: msg.createdAt,
      sequence: msg.sequence,
      deliveryStatus: 'delivered',
      readBy: [],
      isMine: msg.senderId === currentUserId,
    }),
    []
  );

  // Initial load: cache first, then server
  const loadInitial = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setIsLoading(true);
    setError(null);

    try {
      // Try cache first
      const cached = await getCachedMessages(threadId, initialLimit);

      if (cached.length > 0) {
        setMessages(cached.map((m) => toMessage(m)));

        // Update pagination state from cache
        const range = await getCacheSequenceRange(threadId);
        setPagination((prev) => ({
          ...prev,
          oldestSequence: range.oldest,
          newestSequence: range.newest,
          // Assume there's more if we hit the limit
          hasMoreBefore: cached.length >= initialLimit,
        }));
      }

      // Fetch from server (may have newer messages)
      const response = await api.get(`/threads/${threadId}/messages`, {
        params: { limit: initialLimit },
      });

      const serverMessages: CacheableMessage[] = response.data.messages || [];

      if (serverMessages.length > 0) {
        // Cache the server messages
        await cacheMessages(threadId, serverMessages);

        // Update state with server messages
        setMessages(serverMessages.map((m) => toMessage(m)));
        setPagination({
          hasMoreBefore: response.data.has_more_before ?? serverMessages.length >= initialLimit,
          hasMoreAfter: response.data.has_more_after ?? false,
          oldestSequence: response.data.oldest_sequence ?? serverMessages[0]?.sequence ?? null,
          newestSequence:
            response.data.newest_sequence ??
            serverMessages[serverMessages.length - 1]?.sequence ??
            null,
        });
      }
    } catch (err) {
      // If server fails but we have cache, use cache
      if (messages.length === 0) {
        setError(err instanceof Error ? err : new Error('Failed to load messages'));
      }
      console.error('[useMessageHistory] Load error:', err);
    } finally {
      setIsLoading(false);
      loadingRef.current = false;
    }
  }, [threadId, initialLimit, toMessage]);

  // Load older messages (pagination)
  const loadOlder = useCallback(async () => {
    if (loadingRef.current || isLoadingOlder || !pagination.hasMoreBefore) return;

    const oldestSeq = pagination.oldestSequence;
    if (oldestSeq === null) return;

    loadingRef.current = true;
    setIsLoadingOlder(true);

    try {
      // Try cache first
      const cached = await getCachedMessages(threadId, pageSize, oldestSeq);

      if (cached.length > 0) {
        setMessages((prev) => [...cached.map((m) => toMessage(m)), ...prev]);
        setPagination((prev) => ({
          ...prev,
          oldestSequence: cached[0]?.sequence ?? prev.oldestSequence,
          hasMoreBefore: cached.length >= pageSize,
        }));
      }

      // If cache didn't have enough, fetch from server
      if (cached.length < pageSize) {
        const response = await api.get(`/threads/${threadId}/messages`, {
          params: {
            before_sequence: cached.length > 0 ? cached[0].sequence : oldestSeq,
            limit: pageSize,
          },
        });

        const serverMessages: CacheableMessage[] = response.data.messages || [];

        if (serverMessages.length > 0) {
          // Cache and prepend
          await cacheMessages(threadId, serverMessages);
          setMessages((prev) => [...serverMessages.map((m) => toMessage(m)), ...prev]);
          setPagination((prev) => ({
            ...prev,
            hasMoreBefore: response.data.has_more_before ?? false,
            oldestSequence: response.data.oldest_sequence ?? serverMessages[0]?.sequence ?? null,
          }));
        } else {
          // No more messages on server
          setPagination((prev) => ({ ...prev, hasMoreBefore: false }));
        }
      }
    } catch (err) {
      console.error('[useMessageHistory] Load older error:', err);
      // Don't set error for pagination failures, just stop loading
    } finally {
      setIsLoadingOlder(false);
      loadingRef.current = false;
    }
  }, [threadId, pageSize, pagination, isLoadingOlder, toMessage]);

  // Refresh: reload from server
  const refresh = useCallback(async () => {
    setMessages([]);
    setPagination({
      hasMoreBefore: true,
      hasMoreAfter: false,
      oldestSequence: null,
      newestSequence: null,
    });
    await loadInitial();
  }, [loadInitial]);

  // Load on mount
  useEffect(() => {
    loadInitial();
  }, [loadInitial]);

  return {
    messages,
    isLoading,
    isLoadingOlder,
    error,
    hasMoreOlder: pagination.hasMoreBefore,
    loadOlder,
    refresh,
  };
}
