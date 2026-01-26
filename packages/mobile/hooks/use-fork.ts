/**
 * ARCHITECTURE: Hook for forking threads with optimistic UI and error handling.
 * WHY: Encapsulates fork API call with navigation and cache invalidation.
 * TRADEOFF: Simple useState vs react-query, but follows existing codebase patterns.
 */

import { useState, useCallback } from 'react';
import { Alert } from 'react-native';
import { useRouter } from 'expo-router';
import { api } from '@/services/api';

interface ForkParams {
  roomId: string;
  sourceThreadId: string;
  forkAfterMessageId: string;
  title?: string;
}

interface ThreadResponse {
  id: string;
  room_id: string;
  parent_thread_id: string;
  title: string | null;
  message_count: number;
}

interface UseForkThreadReturn {
  forkThread: (params: ForkParams) => Promise<ThreadResponse | null>;
  isForking: boolean;
  error: Error | null;
}

export function useForkThread(): UseForkThreadReturn {
  const router = useRouter();
  const [isForking, setIsForking] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const forkThread = useCallback(
    async (params: ForkParams): Promise<ThreadResponse | null> => {
      setIsForking(true);
      setError(null);

      try {
        const response = await api.post<ThreadResponse>(
          `/threads/${params.sourceThreadId}/fork`,
          {
            source_thread_id: params.sourceThreadId,
            fork_after_message_id: params.forkAfterMessageId,
            title: params.title,
          }
        );

        const newThread = response.data;

        // CONTEXT.md: After forking, navigate immediately to new thread
        // Type assertion needed as dynamic route structure isn't fully typed
        (router.push as (path: string) => void)(
          `/room/${params.roomId}/thread/${newThread.id}`
        );

        return newThread;
      } catch (err) {
        const errorObj = err instanceof Error ? err : new Error('Fork failed');
        setError(errorObj);
        Alert.alert('Fork Failed', 'Could not create branch. Please try again.');
        console.error('[useForkThread] Fork error:', err);
        return null;
      } finally {
        setIsForking(false);
      }
    },
    [router]
  );

  return {
    forkThread,
    isForking,
    error,
  };
}
