/**
 * ARCHITECTURE: Hook for detecting @Claude mentions in message text.
 * WHY: CONTEXT.md requires @Claude detection for explicit LLM invocation.
 * TRADEOFF: Simple regex vs library mention parsing.
 */

import { useCallback, useState } from 'react';

interface UseMentionDetectionOptions {
  onMentionDetected?: (hasMention: boolean) => void;
}

export function useMentionDetection({
  onMentionDetected,
}: UseMentionDetectionOptions = {}) {
  const [hasMention, setHasMention] = useState(false);

  // Detect @Claude mention (case insensitive)
  const detectMention = useCallback(
    (text: string): boolean => {
      // Match @claude or @Claude anywhere in text
      // Also match the encoded format from react-native-controlled-mentions: @[Claude](claude)
      const mentionPattern = /@claude\b|@\[Claude\]\(claude\)/i;
      const detected = mentionPattern.test(text);

      setHasMention(detected);
      onMentionDetected?.(detected);

      return detected;
    },
    [onMentionDetected]
  );

  // Extract plain text content (remove mention markup)
  const extractPlainText = useCallback((text: string): string => {
    // Replace @[Claude](claude) format with @Claude
    return text.replace(/@\[([^\]]+)\]\([^)]+\)/g, '@$1');
  }, []);

  // Check if message should trigger LLM on submit
  const shouldTriggerLLM = useCallback(
    (text: string): boolean => {
      return detectMention(text);
    },
    [detectMention]
  );

  return {
    hasMention,
    detectMention,
    extractPlainText,
    shouldTriggerLLM,
  };
}
