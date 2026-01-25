import { useState, useCallback, useRef, useEffect } from 'react';
import { websocketService } from '@/services/websocket';
import { useTypingStore } from '@/stores/typing-store';

// RESEARCH.md: 500ms debounce for typing_start
const TYPING_DEBOUNCE_MS = 500;
// CONTEXT.md: 3 seconds to clear typing indicator
const TYPING_TIMEOUT_MS = 3000;

/**
 * ARCHITECTURE: Debounced typing indicator with auto-stop.
 * WHY: Reduce WebSocket traffic while maintaining responsive UI.
 * TRADEOFF: 500ms delay on first keystroke vs server load.
 */
export function useTyping() {
  const [isTyping, setIsTyping] = useState(false);
  const typingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { typingUsers, setUserTyping, clearUserTyping } = useTypingStore();

  // Send typing_start with debounce
  const sendTypingStart = useCallback(() => {
    if (!isTyping) {
      setIsTyping(true);
      websocketService.send({
        type: 'typing_start',
        payload: { typing: true },
      });
    }

    // Reset the stop timeout
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
    }

    // Auto-stop after 3 seconds of no activity
    typingTimeoutRef.current = setTimeout(() => {
      setIsTyping(false);
      websocketService.send({
        type: 'typing_stop',
        payload: { typing: false },
      });
    }, TYPING_TIMEOUT_MS);
  }, [isTyping]);

  // Call this on every text change
  const onTextChange = useCallback(
    (text: string) => {
      // Debounce to avoid sending too many typing events
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }

      debounceRef.current = setTimeout(() => {
        if (text.length > 0) {
          sendTypingStart();
        } else {
          // Text cleared, stop typing immediately
          if (isTyping) {
            setIsTyping(false);
            websocketService.send({
              type: 'typing_stop',
              payload: { typing: false },
            });
            if (typingTimeoutRef.current) {
              clearTimeout(typingTimeoutRef.current);
            }
          }
        }
      }, TYPING_DEBOUNCE_MS);
    },
    [sendTypingStart, isTyping]
  );

  // Call when message is sent
  const stopTyping = useCallback(() => {
    if (isTyping) {
      setIsTyping(false);
      websocketService.send({
        type: 'typing_stop',
        payload: { typing: false },
      });
    }

    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
      typingTimeoutRef.current = null;
    }
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
  }, [isTyping]);

  // Handle incoming typing events
  const handleTypingEvent = useCallback(
    (userId: string, displayName: string, isTyping: boolean) => {
      if (isTyping) {
        setUserTyping(userId, displayName);
      } else {
        clearUserTyping(userId);
      }
    },
    [setUserTyping, clearUserTyping]
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current);
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  return {
    isTyping,
    onTextChange,
    stopTyping,
    handleTypingEvent,
    typingUsers: Object.values(typingUsers),
  };
}
