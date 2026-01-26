/**
 * ARCHITECTURE: Hook coordinating LLM store, WebSocket, and message integration.
 * WHY: Single interface for LLM operations with proper event handling.
 * TRADEOFF: Handlers object pattern vs direct hooks - flexibility for wiring.
 */

import { useCallback, useMemo } from 'react';
import { useLLMStore } from '@/stores/llm-store';
import { useMessagesStore } from '@/stores/messages-store';
import { websocketService } from '@/services/websocket';
import type {
  LLMThinkingPayload,
  LLMStreamingPayload,
  LLMDonePayload,
  LLMErrorPayload,
} from '@/services/websocket/types';

interface UseLLMOptions {
  threadId: string;
}

export function useLLM({ threadId }: UseLLMOptions) {
  const {
    isThinking,
    isStreaming,
    partialResponse,
    streamingMessageId,
    activeThreadId,
    startThinking,
    startStreaming,
    appendToken,
    finishStreaming,
    cancelResponse,
  } = useLLMStore();

  const { addMessage } = useMessagesStore();

  // Check if LLM is active in this thread
  const isActiveInThread = activeThreadId === threadId;

  // Event handlers for WebSocket dispatch
  const handleThinking = useCallback(
    (payload: LLMThinkingPayload) => {
      if (payload.thread_id === threadId) {
        startThinking(payload.thread_id);
      }
    },
    [threadId, startThinking]
  );

  const handleStreaming = useCallback(
    (payload: LLMStreamingPayload) => {
      if (payload.thread_id !== threadId) return;

      // Transition from thinking to streaming on first token
      if (isThinking && !isStreaming) {
        startStreaming(payload.message_id);
      }

      appendToken(payload.token);
    },
    [threadId, isThinking, isStreaming, startStreaming, appendToken]
  );

  const handleDone = useCallback(
    (payload: LLMDonePayload) => {
      if (payload.thread_id !== threadId) return;

      // Add complete message to messages store
      addMessage({
        id: payload.message_id,
        threadId: payload.thread_id,
        content: payload.content,
        senderId: 'llm', // Special sender ID for LLM
        senderName: payload.model_used,
        createdAt: new Date().toISOString(),
        deliveryStatus: 'delivered',
        readBy: [],
      });

      // Reset LLM state
      finishStreaming();
    },
    [threadId, addMessage, finishStreaming]
  );

  const handleError = useCallback(
    (payload: LLMErrorPayload) => {
      if (payload.thread_id !== threadId) return;

      // If there was partial content, add it as an error message
      if (payload.partial_content) {
        addMessage({
          id: `llm-error-${Date.now()}`,
          threadId: payload.thread_id,
          content: `${payload.partial_content}\n\n[Error: ${payload.error}]`,
          senderId: 'llm',
          senderName: 'Claude (error)',
          createdAt: new Date().toISOString(),
          deliveryStatus: 'failed',
          readBy: [],
        });
      }

      // Cancel and reset state
      cancelResponse();
    },
    [threadId, addMessage, cancelResponse]
  );

  // Actions for calling LLM
  const summonClaude = useCallback(
    (triggerContent?: string) => {
      websocketService.send({
        type: 'summon_llm',
        payload: {
          thread_id: threadId,
          trigger_content: triggerContent,
        },
      });
    },
    [threadId]
  );

  const cancel = useCallback(() => {
    websocketService.send({
      type: 'cancel_llm',
      payload: { thread_id: threadId },
    });
    cancelResponse();
  }, [threadId, cancelResponse]);

  // Handlers object for WebSocket event wiring
  const handlers = useMemo(
    () => ({
      handleThinking,
      handleStreaming,
      handleDone,
      handleError,
    }),
    [handleThinking, handleStreaming, handleDone, handleError]
  );

  return {
    // State (scoped to whether active in this thread)
    isThinking: isActiveInThread && isThinking,
    isStreaming: isActiveInThread && isStreaming,
    partialResponse: isActiveInThread ? partialResponse : '',
    streamingMessageId: isActiveInThread ? streamingMessageId : null,

    // Actions
    summonClaude,
    cancel,

    // Handlers for WebSocket wiring
    handlers,
  };
}
