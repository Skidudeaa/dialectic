/**
 * ARCHITECTURE: Session restoration hook for app launch.
 * WHY: Users expect to return to where they left off.
 * TRADEOFF: Navigation complexity vs always starting fresh, but better UX.
 */

import { useEffect, useState, useCallback } from 'react';
import { useRouter, useSegments } from 'expo-router';
import { useSessionStore } from '@/stores/session-store';
import { runMigrations } from '@/db';

interface SessionRestoreState {
  isRestoring: boolean;
  isReady: boolean;
  error: Error | null;
}

interface UseSessionRestoreReturn extends SessionRestoreState {
  /** Call after auth check to trigger navigation to last conversation */
  restoreNavigation: () => void;
}

/**
 * Hook for restoring user session on app launch.
 *
 * Handles:
 * 1. Running database migrations
 * 2. Loading last conversation from session store
 * 3. Navigating to last conversation after auth
 *
 * @example
 * const { isReady, restoreNavigation } = useSessionRestore();
 *
 * useEffect(() => {
 *   if (isReady && isAuthenticated) {
 *     restoreNavigation();
 *   }
 * }, [isReady, isAuthenticated]);
 */
export function useSessionRestore(): UseSessionRestoreReturn {
  const [state, setState] = useState<SessionRestoreState>({
    isRestoring: true,
    isReady: false,
    error: null,
  });

  const router = useRouter();
  const segments = useSegments();
  const { lastRoomId, lastThreadId } = useSessionStore();

  // Run database migrations on mount
  useEffect(() => {
    async function initialize() {
      try {
        // Run SQLite migrations
        await runMigrations();

        setState({
          isRestoring: false,
          isReady: true,
          error: null,
        });

        console.log('[SessionRestore] Initialization complete');
      } catch (error) {
        console.error('[SessionRestore] Initialization error:', error);
        setState({
          isRestoring: false,
          isReady: true, // Still mark as ready so app can proceed
          error: error instanceof Error ? error : new Error('Failed to initialize'),
        });
      }
    }

    initialize();
  }, []);

  // Navigate to last conversation
  const restoreNavigation = useCallback(() => {
    // Only restore if we have a saved conversation
    if (!lastRoomId || !lastThreadId) {
      console.log('[SessionRestore] No saved conversation to restore');
      return;
    }

    // Don't restore if already in a conversation route
    // Check if any segment contains 'room' or 'thread' to handle nested routes
    const isInConversation = segments.some(
      (segment) =>
        typeof segment === 'string' &&
        (segment.includes('room') || segment.includes('thread'))
    );

    if (isInConversation) {
      console.log('[SessionRestore] Already in conversation, skipping restore');
      return;
    }

    console.log(
      `[SessionRestore] Restoring to room=${lastRoomId}, thread=${lastThreadId}`
    );

    // Navigate to the conversation
    // Route structure: /(app)/room/[roomId]/thread/[threadId]
    // Using type assertion since room routes will be added in later phase
    router.replace({
      pathname: '/(app)/room/[roomId]/thread/[threadId]',
      params: { roomId: lastRoomId, threadId: lastThreadId },
    } as unknown as Parameters<typeof router.replace>[0]);
  }, [lastRoomId, lastThreadId, segments, router]);

  return {
    ...state,
    restoreNavigation,
  };
}

/**
 * Hook to track current conversation for session persistence.
 * Call this in conversation screens to update session state.
 */
export function useTrackConversation(roomId: string, threadId: string) {
  const { setLastConversation } = useSessionStore();

  useEffect(() => {
    setLastConversation(roomId, threadId);
  }, [roomId, threadId, setLastConversation]);
}
