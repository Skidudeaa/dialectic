/**
 * ARCHITECTURE: Hook for fetching thread genealogy tree from API.
 * WHY: Encapsulates genealogy data fetching with loading/error states.
 * TRADEOFF: Simple useState vs react-query, but follows existing codebase patterns.
 */

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/services/api';

export interface ThreadNode {
  id: string;
  parent_thread_id: string | null;
  fork_point_message_id: string | null;
  title: string | null;
  message_count: number;
  created_at: string;
  depth: number;
  children: ThreadNode[];
}

interface UseGenealogyReturn {
  data: ThreadNode[] | null;
  isLoading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
}

export function useGenealogy(roomId: string | undefined): UseGenealogyReturn {
  const [data, setData] = useState<ThreadNode[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchGenealogy = useCallback(async () => {
    if (!roomId) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await api.get<ThreadNode[]>(`/rooms/${roomId}/genealogy`);
      setData(response.data);
    } catch (err) {
      const errorObj = err instanceof Error ? err : new Error('Failed to fetch genealogy');
      setError(errorObj);
      console.error('[useGenealogy] Fetch error:', err);
    } finally {
      setIsLoading(false);
    }
  }, [roomId]);

  // Fetch on mount and when roomId changes
  useEffect(() => {
    if (roomId) {
      fetchGenealogy();
    }
  }, [roomId, fetchGenealogy]);

  return {
    data,
    isLoading,
    error,
    refetch: fetchGenealogy,
  };
}
