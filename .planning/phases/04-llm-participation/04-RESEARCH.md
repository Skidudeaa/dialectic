# Phase 4: LLM Participation - Research

**Researched:** 2026-01-25
**Domain:** LLM streaming integration, markdown rendering, @mention detection for React Native/Expo
**Confidence:** HIGH

## Summary

This research covers integrating LLM participation into a React Native mobile app where Claude acts as a conversation participant. The phase requires: (1) streaming token-by-token responses via WebSocket, (2) rendering LLM responses with full markdown support, (3) detecting @Claude mentions in user input, and (4) showing "thinking" indicators during response generation.

The existing backend already has streaming capabilities via `providers.py` with both Anthropic and OpenAI providers. The backend streams tokens using Server-Sent Events (SSE) format (`content_block_delta` events). For the mobile client, we need to extend the WebSocket protocol to relay these streaming tokens, add a markdown renderer component, implement mention detection in the message input, and create an animated thinking indicator.

Per CONTEXT.md, Claude messages should appear centered (not left/right like humans), use a different bubble color with an avatar/label, render full markdown, and show pulsing dots while thinking. The @Claude mention should be detected anywhere in the message (not just at the start), styled as bold/colored text, and trigger a response.

**Primary recommendation:** Use `react-native-markdown-display` for markdown rendering, `react-native-controlled-mentions` for @mention detection, `@mrakesh0608/react-native-loading-dots` for the thinking indicator, and extend the existing WebSocket service to handle `llm_streaming` events with progressive text accumulation.

## Standard Stack

The established libraries for LLM participation in React Native:

### Core (Mobile)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `react-native-markdown-display` | ^7.x | Render markdown in messages | 100% CommonMark, native components (not WebView), customizable styling |
| `react-native-controlled-mentions` | ^2.x | @mention detection & highlighting | TypeScript, no native deps, works with TextInput |
| `@mrakesh0608/react-native-loading-dots` | ^1.x | Animated thinking dots | Multiple animation types including 'typing' and 'pulse', customizable |
| Existing WebSocket service | Phase 3 | Real-time streaming transport | Already implemented with reconnection |
| Existing Zustand stores | Phase 3 | State management | Already patterns for messages |

### Backend (Already Implemented)

| Component | Location | Purpose |
|-----------|----------|---------|
| `providers.py` | `dialectic/llm/` | Anthropic/OpenAI streaming via httpx |
| `orchestrator.py` | `dialectic/llm/` | Coordinates LLM calls |
| `prompts.py` | `dialectic/llm/` | Context assembly |
| `handlers.py` | `dialectic/transport/` | WebSocket message handlers |
| `websocket.py` | `dialectic/transport/` | `LLM_THINKING`, `LLM_STREAMING` message types |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `highlight.js` | optional | Code syntax highlighting | If code blocks need highlighting |
| `react-native-reanimated` | ^3.x | Smooth animations | Already in Expo, for thinking indicator |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `react-native-markdown-display` | `react-native-marked` | marked.js-based, less customizable but supports JSX embedding |
| `react-native-controlled-mentions` | `react-native-mentions-editor` | More features but heavier, WhatsApp-style |
| Custom loading dots | `react-native-indicators` | More indicator types but larger bundle |
| WebSocket streaming | HTTP SSE | SSE better for one-way streams but we already have WebSocket |

**Installation (Mobile):**
```bash
cd mobile
npm install react-native-markdown-display react-native-controlled-mentions @mrakesh0608/react-native-loading-dots
```

## Architecture Patterns

### Recommended Project Structure

```
mobile/
├── services/
│   └── websocket/
│       └── index.ts         # Extend to handle llm_streaming
├── stores/
│   ├── messages-store.ts    # Add LLM message type, streaming state
│   └── llm-store.ts         # NEW: LLM-specific state (thinking, streaming)
├── hooks/
│   ├── use-messages.ts      # Extend for LLM messages
│   ├── use-llm.ts           # NEW: LLM invocation hook
│   └── use-mention-input.ts # NEW: @mention detection hook
├── components/
│   ├── ui/
│   │   ├── message-bubble.tsx      # Extend for LLM styling
│   │   ├── llm-message-bubble.tsx  # NEW: Centered Claude bubble
│   │   ├── thinking-indicator.tsx  # NEW: Pulsing dots
│   │   └── markdown-content.tsx    # NEW: Markdown renderer
│   └── chat/
│       └── mention-input.tsx       # NEW: Input with @mention

dialectic/
├── transport/
│   └── handlers.py          # Add streaming handler
└── llm/
    └── orchestrator.py      # Add streaming force_response variant
```

### Pattern 1: LLM Message Store

**What:** Separate store for LLM-specific state (thinking, partial response)
**When to use:** Managing streaming state and partial responses

```typescript
// Source: Extends existing Zustand pattern from Phase 3
// stores/llm-store.ts
import { create } from 'zustand';

interface LLMState {
  // Is Claude currently thinking (before streaming starts)?
  isThinking: boolean;
  // Is Claude currently streaming a response?
  isStreaming: boolean;
  // Partial response being built
  partialResponse: string;
  // Message ID for the streaming response
  streamingMessageId: string | null;
  // Thread ID where LLM is responding
  activeThreadId: string | null;

  // Actions
  startThinking: (threadId: string) => void;
  startStreaming: (messageId: string) => void;
  appendToken: (token: string) => void;
  finishStreaming: () => void;
  cancelResponse: () => void;
  reset: () => void;
}

export const useLLMStore = create<LLMState>()((set) => ({
  isThinking: false,
  isStreaming: false,
  partialResponse: '',
  streamingMessageId: null,
  activeThreadId: null,

  startThinking: (threadId) => set({
    isThinking: true,
    isStreaming: false,
    partialResponse: '',
    streamingMessageId: null,
    activeThreadId: threadId,
  }),

  startStreaming: (messageId) => set({
    isThinking: false,
    isStreaming: true,
    streamingMessageId: messageId,
  }),

  appendToken: (token) => set((state) => ({
    partialResponse: state.partialResponse + token,
  })),

  finishStreaming: () => set({
    isThinking: false,
    isStreaming: false,
    // Keep partialResponse until message is added to main store
  }),

  cancelResponse: () => set({
    isThinking: false,
    isStreaming: false,
    partialResponse: '',
    streamingMessageId: null,
    activeThreadId: null,
  }),

  reset: () => set({
    isThinking: false,
    isStreaming: false,
    partialResponse: '',
    streamingMessageId: null,
    activeThreadId: null,
  }),
}));
```

### Pattern 2: WebSocket Message Types for Streaming

**What:** Extended WebSocket protocol for LLM streaming events
**When to use:** All LLM response communication

```typescript
// Source: Extend mobile/services/websocket/types.ts
// New inbound message types for LLM

export type InboundMessageType =
  | 'message_created'
  | 'user_joined'
  | 'user_left'
  | 'user_typing'
  | 'presence_update'
  | 'delivery_receipt'
  | 'read_receipt'
  | 'thread_created'
  | 'error'
  | 'pong'
  // NEW: LLM-specific events
  | 'llm_thinking'      // Claude is processing (before tokens)
  | 'llm_streaming'     // Token chunk received
  | 'llm_done'          // Streaming complete
  | 'llm_error';        // LLM call failed

// Payload types for new events
export interface LLMThinkingPayload {
  thread_id: string;
  message_id?: string;  // Placeholder message ID if needed
}

export interface LLMStreamingPayload {
  thread_id: string;
  message_id: string;
  token: string;        // The streamed token/chunk
  index: number;        // Token position (for ordering)
}

export interface LLMDonePayload {
  thread_id: string;
  message_id: string;
  content: string;      // Full final content
  model_used: string;
}

export interface LLMErrorPayload {
  thread_id: string;
  error: string;
  partial_content?: string;  // What was generated before error
}

// New outbound type
export type OutboundMessageType =
  | 'send_message'
  | 'typing_start'
  | 'typing_stop'
  | 'presence_heartbeat'
  | 'presence_update'
  | 'message_delivered'
  | 'message_read'
  | 'ping'
  // NEW
  | 'summon_llm'       // Explicit @Claude invocation
  | 'cancel_llm';      // Cancel in-progress response

export interface SummonLLMPayload {
  thread_id: string;
  // Optional: specific message content that triggered summon
  trigger_content?: string;
}
```

### Pattern 3: Streaming Message Handler

**What:** Handle progressive token display on the mobile client
**When to use:** Processing `llm_streaming` WebSocket events

```typescript
// Source: Mobile client pattern
// hooks/use-llm.ts
import { useCallback, useEffect } from 'react';
import { useLLMStore } from '@/stores/llm-store';
import { useMessagesStore } from '@/stores/messages-store';
import { websocketService } from '@/services/websocket';
import type {
  LLMThinkingPayload,
  LLMStreamingPayload,
  LLMDonePayload,
  LLMErrorPayload
} from '@/services/websocket/types';

export function useLLM(threadId: string) {
  const {
    isThinking,
    isStreaming,
    partialResponse,
    activeThreadId,
    startThinking,
    startStreaming,
    appendToken,
    finishStreaming,
    cancelResponse,
  } = useLLMStore();

  const { addMessage } = useMessagesStore();

  // Handle llm_thinking event
  const handleThinking = useCallback((payload: LLMThinkingPayload) => {
    if (payload.thread_id === threadId) {
      startThinking(threadId);
    }
  }, [threadId, startThinking]);

  // Handle llm_streaming event
  const handleStreaming = useCallback((payload: LLMStreamingPayload) => {
    if (payload.thread_id !== threadId) return;

    if (!useLLMStore.getState().isStreaming) {
      // First token - transition from thinking to streaming
      startStreaming(payload.message_id);
    }

    appendToken(payload.token);
  }, [threadId, startStreaming, appendToken]);

  // Handle llm_done event
  const handleDone = useCallback((payload: LLMDonePayload) => {
    if (payload.thread_id !== threadId) return;

    // Add complete message to store
    addMessage({
      id: payload.message_id,
      threadId: payload.thread_id,
      content: payload.content,
      senderId: 'claude',  // Special sender ID for LLM
      senderName: 'Claude',
      createdAt: new Date().toISOString(),
      deliveryStatus: 'delivered',
      readBy: [],
    });

    finishStreaming();
  }, [threadId, addMessage, finishStreaming]);

  // Handle llm_error event
  const handleError = useCallback((payload: LLMErrorPayload) => {
    if (payload.thread_id !== threadId) return;

    // If we have partial content, still show it with error indicator
    if (payload.partial_content) {
      addMessage({
        id: `error-${Date.now()}`,
        threadId: payload.thread_id,
        content: payload.partial_content + '\n\n[Response interrupted]',
        senderId: 'claude',
        senderName: 'Claude',
        createdAt: new Date().toISOString(),
        deliveryStatus: 'failed',
        readBy: [],
      });
    }

    cancelResponse();
  }, [threadId, addMessage, cancelResponse]);

  // Summon Claude explicitly
  const summonClaude = useCallback((triggerContent?: string) => {
    websocketService.send({
      type: 'summon_llm',
      payload: {
        thread_id: threadId,
        trigger_content: triggerContent,
      },
    });
  }, [threadId]);

  // Cancel in-progress response
  const cancel = useCallback(() => {
    websocketService.send({
      type: 'cancel_llm',
      payload: { thread_id: threadId },
    });
    cancelResponse();
  }, [threadId, cancelResponse]);

  return {
    isThinking: isThinking && activeThreadId === threadId,
    isStreaming: isStreaming && activeThreadId === threadId,
    partialResponse,
    summonClaude,
    cancel,
    handlers: {
      handleThinking,
      handleStreaming,
      handleDone,
      handleError,
    },
  };
}
```

### Pattern 4: Markdown Message Component

**What:** Render LLM responses with full markdown support
**When to use:** Displaying Claude messages

```typescript
// Source: react-native-markdown-display official docs
// components/ui/markdown-content.tsx
import React, { useMemo } from 'react';
import { StyleSheet, useColorScheme } from 'react-native';
import Markdown, { MarkdownIt } from 'react-native-markdown-display';

interface MarkdownContentProps {
  content: string;
  isLLM?: boolean;
}

// CONTEXT.md: Full markdown rendering (bold, italic, lists, code blocks)
export function MarkdownContent({ content, isLLM = false }: MarkdownContentProps) {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';

  const styles = useMemo(() => StyleSheet.create({
    body: {
      fontSize: 16,
      lineHeight: 24,
      color: isLLM ? '#1f2937' : (isDark ? '#f9fafb' : '#1f2937'),
    },
    heading1: {
      fontSize: 24,
      fontWeight: 'bold',
      marginTop: 12,
      marginBottom: 8,
    },
    heading2: {
      fontSize: 20,
      fontWeight: 'bold',
      marginTop: 10,
      marginBottom: 6,
    },
    heading3: {
      fontSize: 18,
      fontWeight: '600',
      marginTop: 8,
      marginBottom: 4,
    },
    paragraph: {
      marginTop: 0,
      marginBottom: 8,
    },
    bullet_list: {
      marginLeft: 8,
    },
    ordered_list: {
      marginLeft: 8,
    },
    list_item: {
      marginBottom: 4,
    },
    code_inline: {
      backgroundColor: isDark ? '#374151' : '#f3f4f6',
      paddingHorizontal: 6,
      paddingVertical: 2,
      borderRadius: 4,
      fontFamily: 'monospace',
      fontSize: 14,
    },
    code_block: {
      backgroundColor: isDark ? '#1f2937' : '#f3f4f6',
      padding: 12,
      borderRadius: 8,
      marginVertical: 8,
      fontFamily: 'monospace',
      fontSize: 14,
    },
    fence: {
      backgroundColor: isDark ? '#1f2937' : '#f3f4f6',
      padding: 12,
      borderRadius: 8,
      marginVertical: 8,
      fontFamily: 'monospace',
      fontSize: 14,
    },
    blockquote: {
      backgroundColor: isDark ? '#374151' : '#f9fafb',
      borderLeftWidth: 4,
      borderLeftColor: '#6366f1',
      paddingLeft: 12,
      paddingVertical: 4,
      marginVertical: 8,
    },
    link: {
      color: '#6366f1',
      textDecorationLine: 'underline',
    },
    strong: {
      fontWeight: 'bold',
    },
    em: {
      fontStyle: 'italic',
    },
  }), [isDark, isLLM]);

  return (
    <Markdown style={styles}>
      {content}
    </Markdown>
  );
}
```

### Pattern 5: LLM Message Bubble (Centered)

**What:** Centered message bubble for Claude with distinct styling
**When to use:** Rendering Claude's messages in the chat

```typescript
// Source: CONTEXT.md decisions
// components/ui/llm-message-bubble.tsx
import React from 'react';
import { View, Text, StyleSheet, Image } from 'react-native';
import { MarkdownContent } from './markdown-content';
import { ThinkingIndicator } from './thinking-indicator';

interface LLMMessageBubbleProps {
  content?: string;
  isThinking?: boolean;
  isStreaming?: boolean;
  modelUsed?: string;
  createdAt?: string;
}

// CONTEXT.md: Claude messages centered, different bubble color + avatar
export function LLMMessageBubble({
  content,
  isThinking = false,
  isStreaming = false,
  modelUsed,
  createdAt,
}: LLMMessageBubbleProps) {
  return (
    <View style={styles.container}>
      {/* Avatar/Label */}
      <View style={styles.header}>
        <View style={styles.avatar}>
          {/* CONTEXT.md: Avatar is a friendly character illustration */}
          <Text style={styles.avatarText}>C</Text>
        </View>
        <Text style={styles.label}>Claude</Text>
      </View>

      {/* Message Bubble */}
      <View style={styles.bubble}>
        {isThinking ? (
          <ThinkingIndicator />
        ) : content ? (
          <MarkdownContent content={content} isLLM />
        ) : null}

        {/* Streaming indicator */}
        {isStreaming && !isThinking && (
          <View style={styles.streamingCursor} />
        )}
      </View>

      {/* Metadata */}
      {createdAt && !isThinking && (
        <Text style={styles.timestamp}>
          {new Date(createdAt).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    // CONTEXT.md: Claude messages centered
    alignSelf: 'center',
    alignItems: 'center',
    maxWidth: '90%',
    marginVertical: 12,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  avatar: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#6366f1', // Indigo - Claude's color
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  avatarText: {
    color: '#ffffff',
    fontWeight: 'bold',
    fontSize: 14,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6366f1',
  },
  bubble: {
    // CONTEXT.md: Different bubble color for Claude
    backgroundColor: '#eef2ff', // Indigo-50 - subtle Claude color
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 16,
    minWidth: 120,
  },
  streamingCursor: {
    width: 2,
    height: 16,
    backgroundColor: '#6366f1',
    marginLeft: 2,
    opacity: 0.7,
  },
  timestamp: {
    marginTop: 4,
    fontSize: 11,
    color: '#9ca3af',
  },
});
```

### Pattern 6: Thinking Indicator

**What:** Animated pulsing dots while Claude is processing
**When to use:** After @Claude mention before streaming starts

```typescript
// Source: @mrakesh0608/react-native-loading-dots
// components/ui/thinking-indicator.tsx
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { LoadingDots } from '@mrakesh0608/react-native-loading-dots';

interface ThinkingIndicatorProps {
  label?: string;
}

// CONTEXT.md: Pulsing dots indicator (three animated dots like iMessage)
export function ThinkingIndicator({ label = 'Claude is thinking' }: ThinkingIndicatorProps) {
  return (
    <View style={styles.container}>
      <LoadingDots
        animation="typing"  // iMessage-style typing animation
        dots={3}
        size={8}
        color="#6366f1"
        spacing={4}
      />
      {label && <Text style={styles.label}>{label}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    paddingHorizontal: 4,
  },
  label: {
    marginLeft: 12,
    fontSize: 14,
    color: '#6b7280',
    fontStyle: 'italic',
  },
});
```

### Pattern 7: @Mention Input

**What:** Text input with @Claude mention detection and highlighting
**When to use:** Message composer

```typescript
// Source: react-native-controlled-mentions
// components/chat/mention-input.tsx
import React, { useCallback, useState, useMemo } from 'react';
import { View, TextInput, StyleSheet, FlatList, TouchableOpacity, Text } from 'react-native';
import {
  MentionInput,
  MentionSuggestionsProps,
  Suggestion,
} from 'react-native-controlled-mentions';

interface MentionInputProps {
  value: string;
  onChange: (text: string) => void;
  onSubmit: () => void;
  onMentionDetected?: (mentioned: boolean) => void;
  placeholder?: string;
}

// CONTEXT.md: @Claude detected anywhere in message
// CONTEXT.md: Styled as bold/colored text (not a chip)
const mentionTriggers = {
  mention: {
    trigger: '@',
    textStyle: {
      fontWeight: 'bold' as const,
      color: '#6366f1', // Indigo - Claude's color
    },
    // Only "Claude" is a valid mention target
    isInsertSpaceAfterMention: true,
  },
};

// CONTEXT.md: Either autocomplete or direct typing works
const suggestions: Suggestion[] = [
  { id: 'claude', name: 'Claude' },
];

export function MentionComposer({
  value,
  onChange,
  onSubmit,
  onMentionDetected,
  placeholder = 'Type a message...',
}: MentionInputProps) {
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [keyword, setKeyword] = useState('');

  // CONTEXT.md: @Claude detected anywhere in message triggers response
  const detectMention = useCallback((text: string) => {
    // Check for @Claude pattern (case insensitive)
    const hasMention = /@claude/i.test(text);
    onMentionDetected?.(hasMention);
  }, [onMentionDetected]);

  // Filter suggestions based on keyword
  const filteredSuggestions = useMemo(() => {
    if (!keyword) return suggestions;
    return suggestions.filter((s) =>
      s.name.toLowerCase().includes(keyword.toLowerCase())
    );
  }, [keyword]);

  const renderSuggestions: (props: MentionSuggestionsProps) => React.ReactNode = useCallback(
    ({ keyword: kw, onSuggestionPress }) => {
      setKeyword(kw || '');
      setShowSuggestions(!!kw);

      if (!kw) return null;

      return (
        <View style={styles.suggestionsContainer}>
          {filteredSuggestions.map((suggestion) => (
            <TouchableOpacity
              key={suggestion.id}
              style={styles.suggestionItem}
              onPress={() => onSuggestionPress(suggestion)}
            >
              <View style={styles.suggestionAvatar}>
                <Text style={styles.suggestionAvatarText}>C</Text>
              </View>
              <Text style={styles.suggestionText}>{suggestion.name}</Text>
            </TouchableOpacity>
          ))}
        </View>
      );
    },
    [filteredSuggestions]
  );

  const handleChange = useCallback((text: string) => {
    onChange(text);
    detectMention(text);
  }, [onChange, detectMention]);

  return (
    <View style={styles.container}>
      <MentionInput
        value={value}
        onChange={handleChange}
        partTypes={[
          {
            trigger: '@',
            renderSuggestions,
            textStyle: mentionTriggers.mention.textStyle,
            isInsertSpaceAfterMention: true,
          },
        ]}
        placeholder={placeholder}
        placeholderTextColor="#9ca3af"
        style={styles.input}
        multiline
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  input: {
    fontSize: 16,
    paddingHorizontal: 16,
    paddingVertical: 12,
    maxHeight: 120,
  },
  suggestionsContainer: {
    position: 'absolute',
    bottom: '100%',
    left: 0,
    right: 0,
    backgroundColor: '#ffffff',
    borderTopLeftRadius: 12,
    borderTopRightRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    borderBottomWidth: 0,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: -2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 4,
  },
  suggestionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
  },
  suggestionAvatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#6366f1',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  suggestionAvatarText: {
    color: '#ffffff',
    fontWeight: 'bold',
    fontSize: 14,
  },
  suggestionText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
  },
});
```

### Anti-Patterns to Avoid

- **Blocking UI during LLM call:** Never await the full response; always stream progressively
- **Re-rendering on every token:** Batch token updates (every 50-100ms) to avoid excessive renders
- **No cancel mechanism:** Always provide a way to stop in-progress responses
- **WebView for markdown:** WebView is slow and breaks native feel; use native markdown renderer
- **Ignoring partial responses on error:** If streaming fails mid-response, show what was generated
- **Sending @Claude on every keystroke:** Only detect mention on submit or with debounce

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Markdown rendering | Custom parser | `react-native-markdown-display` | CommonMark compliance, edge cases, code blocks |
| @mention detection | Regex in TextInput | `react-native-controlled-mentions` | Cursor position, selection handling, styling |
| Loading dots animation | Manual Animated API | `@mrakesh0608/react-native-loading-dots` | Smooth animations, timing, cleanup |
| Token batching | Manual setInterval | requestAnimationFrame pattern | Frame-aligned updates, proper cleanup |
| Context truncation | Simple slice | Backend smart truncation | Semantic priority, token counting |

**Key insight:** Streaming UI looks simple but has subtle UX issues: cursor position during typing, animation timing, text measurement for bubble sizing, handling rapid updates without jank. Libraries handle these.

## Common Pitfalls

### Pitfall 1: Token Flood Causing UI Jank

**What goes wrong:** UI becomes sluggish or stuttery during fast token streaming
**Why it happens:** Re-rendering on every token (can be 10-50 per second)
**How to avoid:**
- Batch token updates using requestAnimationFrame
- Update state at most every 50-100ms
- Use `useMemo` for expensive markdown parsing
**Warning signs:** Laggy typing, dropped frames, unresponsive UI during streaming

### Pitfall 2: Partial Response Lost on Error

**What goes wrong:** User loses 2000+ words of response when connection drops at end
**Why it happens:** Only storing final response, not accumulating tokens
**How to avoid:**
- Store `partialResponse` in LLM store throughout streaming
- On error, offer to show partial + retry button
- Per CONTEXT.md: "On streaming failure: show partial response + retry button"
**Warning signs:** Users complaining about lost responses

### Pitfall 3: Mention Detection Race Condition

**What goes wrong:** Message sent before @Claude detection triggers
**Why it happens:** Async detection finishing after submit
**How to avoid:**
- Detect mention synchronously on submit (regex check)
- Don't rely solely on autocomplete selection
- Per CONTEXT.md: "@Claude typed directly also triggers"
**Warning signs:** @Claude in message but no response

### Pitfall 4: Thinking Indicator Not Clearing

**What goes wrong:** "Claude is thinking" stuck on screen indefinitely
**Why it happens:** Missing `llm_done` or `llm_error` handler, error in streaming
**How to avoid:**
- Always handle both success and error paths
- Add timeout (e.g., 120 seconds) that auto-clears with error
- Reset state on thread switch or disconnect
**Warning signs:** Stuck indicators, UI showing thinking when response is done

### Pitfall 5: Multiple Rapid Mentions Creating Chaos

**What goes wrong:** User types "@Claude @Claude @Claude" and gets 3 responses
**Why it happens:** Each mention triggering separate invocation
**How to avoid:**
- Per CONTEXT.md: "Multiple rapid mentions batched into combined response"
- Debounce mention triggers (e.g., 500ms after last mention)
- Only one active LLM response per thread at a time
**Warning signs:** Duplicate responses, overlapping streaming

### Pitfall 6: Markdown Rendering Breaking Layout

**What goes wrong:** Code blocks overflow, images break bubble, lists misaligned
**Why it happens:** Markdown content dimensions not constrained
**How to avoid:**
- Set maxWidth on markdown container
- Wrap code blocks in ScrollView horizontal
- Test with extreme content (very long code, nested lists)
**Warning signs:** Content overflowing screen edges, broken layouts

### Pitfall 7: Cancel Button Not Actually Canceling

**What goes wrong:** Cancel clicked but response keeps streaming
**Why it happens:** Backend not receiving or honoring cancel signal
**How to avoid:**
- Implement `cancel_llm` WebSocket message type
- Backend must abort the httpx stream on cancel
- Client must immediately clear UI state on cancel
**Warning signs:** Response continues after cancel, duplicate messages

## Code Examples

### Backend: Streaming Handler

```python
# Source: Extend dialectic/transport/handlers.py
# Add streaming support to MessageHandler

async def _handle_summon_llm(self, conn: Connection, payload: dict) -> None:
    """Handle explicit @Claude summon from client."""
    thread_id = UUID(payload["thread_id"])
    trigger_content = payload.get("trigger_content")

    # Send thinking indicator
    await self.connections.broadcast(conn.room_id, OutboundMessage(
        type=MessageTypes.LLM_THINKING,
        payload={"thread_id": str(thread_id)},
    ))

    # Get context
    room_row = await self.db.fetchrow("SELECT * FROM rooms WHERE id = $1", conn.room_id)
    room = Room(**dict(room_row))
    thread_row = await self.db.fetchrow("SELECT * FROM threads WHERE id = $1", thread_id)
    thread = Thread(**dict(thread_row))

    user_rows = await self.db.fetch(
        """SELECT u.* FROM users u
           JOIN room_memberships rm ON u.id = rm.user_id
           WHERE rm.room_id = $1""",
        conn.room_id
    )
    users = [User(**dict(row)) for row in user_rows]

    from operations import get_thread_messages
    messages = await get_thread_messages(self.db, thread_id, include_ancestry=True)
    memories = await self.memory.get_context_for_prompt(conn.room_id)

    # Call streaming LLM
    await self._stream_llm_response(
        room=room,
        thread=thread,
        users=users,
        messages=messages,
        memories=memories,
    )

async def _stream_llm_response(
    self,
    room: Room,
    thread: Thread,
    users: list[User],
    messages: list[Message],
    memories: list[Memory],
) -> None:
    """Stream LLM response token by token."""

    prompt = self.llm.prompt_builder.build(
        room=room,
        users=users,
        messages=messages,
        memories=memories,
        is_provoker=False,
    )

    router = self.llm._get_router(room)
    request = LLMRequest(
        messages=prompt.messages,
        system=prompt.system,
        model=room.primary_model,
        stream=True,  # Enable streaming
    )

    message_id = uuid4()
    token_index = 0
    full_content = ""

    try:
        # Get the streaming provider
        provider = router._get_provider()

        async for token in provider.stream(request):
            full_content += token

            # Broadcast token to room
            await self.connections.broadcast(room.id, OutboundMessage(
                type=MessageTypes.LLM_STREAMING,
                payload={
                    "thread_id": str(thread.id),
                    "message_id": str(message_id),
                    "token": token,
                    "index": token_index,
                },
            ))
            token_index += 1

        # Persist complete message
        response_message = await self.llm._persist_response(
            thread=thread,
            content=full_content,
            speaker_type=SpeakerType.LLM_PRIMARY,
            model_used=room.primary_model,
            prompt_hash="",  # TODO: compute hash
            token_count=0,   # TODO: track tokens
        )

        # Send completion signal
        await self.connections.broadcast(room.id, OutboundMessage(
            type=MessageTypes.LLM_DONE,
            payload={
                "thread_id": str(thread.id),
                "message_id": str(response_message.id),
                "content": full_content,
                "model_used": room.primary_model,
            },
        ))

    except Exception as e:
        logger.exception(f"Streaming error: {e}")
        await self.connections.broadcast(room.id, OutboundMessage(
            type=MessageTypes.LLM_ERROR,
            payload={
                "thread_id": str(thread.id),
                "error": str(e),
                "partial_content": full_content if full_content else None,
            },
        ))
```

### Mobile: Message Handler Extension

```typescript
// Source: Extend mobile/hooks/use-websocket.ts or similar
// Handle new LLM message types

import { useLLMStore } from '@/stores/llm-store';

// In your WebSocket message handler:
const handleMessage = (message: InboundMessage) => {
  switch (message.type) {
    case 'llm_thinking':
      useLLMStore.getState().startThinking(message.payload.thread_id);
      break;

    case 'llm_streaming': {
      const { thread_id, message_id, token } = message.payload;
      const state = useLLMStore.getState();

      if (!state.isStreaming) {
        state.startStreaming(message_id);
      }
      state.appendToken(token);
      break;
    }

    case 'llm_done': {
      const { message_id, thread_id, content, model_used } = message.payload;

      // Add to messages store
      useMessagesStore.getState().addMessage({
        id: message_id,
        threadId: thread_id,
        content,
        senderId: 'claude',
        senderName: 'Claude',
        createdAt: new Date().toISOString(),
        deliveryStatus: 'delivered',
        readBy: [],
      });

      useLLMStore.getState().finishStreaming();
      break;
    }

    case 'llm_error': {
      const { thread_id, error, partial_content } = message.payload;

      if (partial_content) {
        useMessagesStore.getState().addMessage({
          id: `partial-${Date.now()}`,
          threadId: thread_id,
          content: partial_content + '\n\n[Response interrupted]',
          senderId: 'claude',
          senderName: 'Claude',
          createdAt: new Date().toISOString(),
          deliveryStatus: 'failed',
          readBy: [],
        });
      }

      useLLMStore.getState().cancelResponse();
      break;
    }

    // ... existing handlers
  }
};
```

### Context Truncation Strategy

```typescript
// Source: CONTEXT.md decisions
// utils/context-truncation.ts

interface Message {
  id: string;
  content: string;
  speaker_type: 'human' | 'llm_primary' | 'llm_provoker';
  is_at_claude_exchange: boolean;  // Was this or reply to @Claude?
}

// CONTEXT.md: Smart truncation prioritizing recent + @Claude exchanges
export function truncateContext(
  messages: Message[],
  maxTokens: number,
  estimateTokens: (text: string) => number
): Message[] {
  // Always include most recent messages
  const RECENT_COUNT = 10;

  // Separate messages into priority tiers
  const recent = messages.slice(-RECENT_COUNT);
  const atClaudeExchanges = messages
    .slice(0, -RECENT_COUNT)
    .filter(m => m.is_at_claude_exchange);
  const other = messages
    .slice(0, -RECENT_COUNT)
    .filter(m => !m.is_at_claude_exchange);

  const result: Message[] = [...recent];
  let tokenCount = recent.reduce((sum, m) => sum + estimateTokens(m.content), 0);

  // Add @Claude exchanges (higher priority)
  for (const msg of atClaudeExchanges.reverse()) {  // Newest first
    const msgTokens = estimateTokens(msg.content);
    if (tokenCount + msgTokens <= maxTokens) {
      result.unshift(msg);
      tokenCount += msgTokens;
    }
  }

  // Fill remaining space with other messages
  for (const msg of other.reverse()) {
    const msgTokens = estimateTokens(msg.content);
    if (tokenCount + msgTokens <= maxTokens) {
      result.unshift(msg);
      tokenCount += msgTokens;
    }
  }

  return result;
}

// Simple token estimation (4 chars = ~1 token)
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Full response then display | Token-by-token streaming | 2023 (ChatGPT) | Dramatically better perceived latency |
| WebView for markdown | Native markdown components | 2022+ | 60fps rendering, native feel |
| Blocking LLM calls | Async streaming via WebSocket | Standard | Non-blocking UI |
| Single mention pattern | Multiple trigger types | 2024+ | Flexible @mention, #hashtag, etc. |

**Deprecated/outdated:**
- WebView-based markdown: Use native components
- Polling for LLM status: Use WebSocket events
- Full response before display: Stream tokens

## Open Questions

Things that couldn't be fully resolved:

1. **Token batching interval**
   - What we know: 50-100ms batching recommended
   - What's unclear: Optimal interval for this specific app
   - Recommendation: Start with 50ms, adjust based on testing

2. **Context window size for mobile**
   - What we know: Claude 3.5 Sonnet has 200k tokens
   - What's unclear: How much context feels appropriate for mobile chat
   - Recommendation: Default to last 50 messages + smart truncation

3. **Cancel mechanism backend implementation**
   - What we know: Need to abort httpx stream
   - What's unclear: Exact cancellation flow with asyncpg transaction
   - Recommendation: Use asyncio.CancelledError, test thoroughly

4. **Offline @Claude mention behavior**
   - What we know: Message queued offline, mention detected
   - What's unclear: Should offline @Claude queue or warn user?
   - Recommendation: Show warning "Claude responses require connection"

## Sources

### Primary (HIGH confidence)
- [react-native-markdown-display GitHub](https://github.com/iamacup/react-native-markdown-display) - Markdown rendering API
- [react-native-controlled-mentions GitHub](https://github.com/dabakovich/react-native-controlled-mentions) - Mention detection patterns
- [@mrakesh0608/react-native-loading-dots GitHub](https://github.com/mrakesh0608/react-native-loading-dots) - Animation types and props
- [Anthropic Streaming API Docs](https://platform.claude.com/docs/en/build-with-claude/streaming) - SSE event format
- Existing codebase: `dialectic/llm/providers.py` - Streaming implementation

### Secondary (MEDIUM confidence)
- [Ably WebSocket React Native](https://ably.com/topic/websockets-react-native) - Mobile streaming patterns
- [PowerSync WebSocket vs HTTP Streaming](https://www.powersync.com/blog/websockets-as-alternative-to-http-streaming-in-react-native) - Streaming architecture
- [FlowToken GitHub](https://github.com/Ephibbs/flowtoken) - Token animation patterns
- [Context Window Management](https://www.getmaxim.ai/articles/context-window-management-strategies-for-long-context-ai-agents-and-chatbots/) - Truncation strategies

### Tertiary (LOW confidence)
- WebSearch results for mobile LLM chat patterns
- Medium articles on streaming implementations

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Well-maintained libraries with active GitHub repos
- Architecture patterns: HIGH - Based on existing codebase patterns + verified docs
- Streaming protocol: HIGH - Anthropic official docs + existing providers.py
- Pitfalls: MEDIUM - Combination of docs and community reports
- Context truncation: MEDIUM - General best practices, specific implementation is Claude's discretion

**Research date:** 2026-01-25
**Valid until:** 2026-02-25 (30 days - stable ecosystem)
