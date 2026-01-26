/**
 * ARCHITECTURE: Auto-save draft with debouncing.
 * WHY: Prevent lost messages when app is killed or backgrounded.
 * TRADEOFF: 500ms save delay vs immediate, but reduces storage writes.
 */

import { useCallback, useEffect, useRef } from 'react';
import { useSessionStore } from '@/stores/session-store';

const DRAFT_SAVE_DELAY_MS = 500;

interface UseDraftReturn {
  /** Initial draft content to populate input */
  initialDraft: string;
  /** Call on every text change (debounced internally) */
  saveDraft: (content: string) => void;
  /** Call when message is sent successfully */
  discardDraft: () => void;
}

/**
 * Hook for managing message drafts with auto-save.
 *
 * @param threadId - The thread to manage draft for
 * @returns Draft operations and initial content
 *
 * @example
 * const { initialDraft, saveDraft, discardDraft } = useDraft(threadId);
 *
 * // In TextInput
 * <TextInput
 *   defaultValue={initialDraft}
 *   onChangeText={saveDraft}
 * />
 *
 * // On send success
 * discardDraft();
 */
export function useDraft(threadId: string): UseDraftReturn {
  const { getDraft, setDraft, clearDraft } = useSessionStore();
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef<string>('');

  // Get initial draft synchronously (MMKV is sync)
  const initialDraft = getDraft(threadId) || '';

  // Track what we've saved to avoid redundant writes
  useEffect(() => {
    lastSavedRef.current = initialDraft;
  }, [initialDraft]);

  const saveDraft = useCallback(
    (content: string) => {
      // Skip if unchanged
      if (content === lastSavedRef.current) return;

      // Clear any pending save
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }

      // Debounce the save
      timeoutRef.current = setTimeout(() => {
        if (content.trim()) {
          setDraft(threadId, content);
        } else {
          // Clear draft if content is empty/whitespace
          clearDraft(threadId);
        }
        lastSavedRef.current = content;
      }, DRAFT_SAVE_DELAY_MS);
    },
    [threadId, setDraft, clearDraft]
  );

  const discardDraft = useCallback(() => {
    // Cancel any pending save
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    // Clear the draft
    clearDraft(threadId);
    lastSavedRef.current = '';
  }, [threadId, clearDraft]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return {
    initialDraft,
    saveDraft,
    discardDraft,
  };
}
