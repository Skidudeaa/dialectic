# Phase 5: Session & History - Research

**Researched:** 2026-01-25
**Domain:** Conversation persistence, pagination, search, and session continuity for React Native/Expo mobile app
**Confidence:** HIGH

## Summary

This research covers implementing conversation persistence, bidirectional pagination, search (local and server-side), and session continuity for the Dialectic mobile app. The phase requires loading message history on app restart, smooth upward pagination for older messages, search within and across conversations, and remembering the user's exact position when returning to the app.

The existing backend already has a messages table with sequence numbers, an events endpoint for gap sync, and pgvector for semantic memory search. The mobile app has MMKV for the offline queue (from Phase 3) and a messages store with optimistic updates. This phase extends this foundation with local SQLite caching for larger message storage, FlashList v2 for performant bidirectional scrolling, and full-text search on both client (SQLite FTS5) and server (PostgreSQL GIN indexes).

The key insight is that MMKV (already installed) is ideal for small, frequently-accessed data like drafts, scroll positions, and settings, while expo-sqlite with Drizzle ORM handles larger datasets like cached messages (500 per conversation as per CONTEXT.md). FlashList v2's built-in `maintainVisibleContentPosition` prop solves the bidirectional scroll problem for chat interfaces.

**Primary recommendation:** Use FlashList v2 for message lists with `maintainVisibleContentPosition` enabled, expo-sqlite with Drizzle ORM for local message cache (500 messages/conversation), MMKV for drafts and scroll positions, PostgreSQL full-text search with GIN indexes for server-side search, and SQLite FTS5 for instant local search. Implement cursor-based pagination using the existing message sequence numbers.

## Standard Stack

The established libraries for session history and search in Expo/React Native:

### Core (Mobile)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@shopify/flash-list` | ^2.x | Virtualized message list | 10x faster than FlatList, built-in scroll position maintenance |
| `expo-sqlite` | ~16.x | Local message cache | Native Expo package, supports FTS5, encryption-ready |
| `drizzle-orm` | ~0.44.x | Type-safe SQLite queries | Full TypeScript support, reactive queries, migrations |
| `react-native-mmkv` | ^4.1.x | Drafts, scroll positions, settings | Already installed, 30x faster than AsyncStorage for small data |
| `zustand` | ^5.x | State management | Already in use, persist middleware for session state |

### Core (Backend Extensions)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PostgreSQL GIN index | built-in | Full-text search | 3x faster lookups than GiST, handles large message tables |
| `to_tsvector` | built-in | Text vectorization | Linguistic features (stemming, stop words) |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `babel-plugin-inline-import` | ^3.x | Bundle SQL migrations | Required for Drizzle + Expo |
| `@tanstack/react-query` | ^5.x | Server state management | Optional for search results caching |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| FlashList v2 | FlatList | FlatList lacks automatic scroll position maintenance |
| expo-sqlite | WatermelonDB | WatermelonDB more complex, better for sync-heavy apps |
| Drizzle ORM | Raw SQL | Raw SQL faster but no type safety, manual migrations |
| GIN index | ILIKE | ILIKE simple but O(n) scans, GIN is O(log n) |
| FTS5 | Basic LIKE | LIKE slower, no ranking, no stemming |

**Installation (Mobile):**
```bash
cd mobile
npx expo install @shopify/flash-list expo-sqlite
npm install drizzle-orm
npm install --save-dev drizzle-kit babel-plugin-inline-import
```

## Architecture Patterns

### Recommended Project Structure

```
mobile/
├── db/
│   ├── index.ts              # Database connection, Drizzle setup
│   ├── schema.ts             # Message cache, drafts, session tables
│   ├── migrations/           # SQL migration files (bundled)
│   └── queries/
│       ├── messages.ts       # Message cache queries
│       ├── search.ts         # Local search queries (FTS5)
│       └── session.ts        # Session state queries
├── services/
│   ├── api.ts                # Existing API client
│   ├── sync/                 # Existing offline queue, gap sync
│   └── history/
│       ├── message-cache.ts  # Cache management (500 msg limit)
│       ├── search-service.ts # Local + remote search coordination
│       └── session-service.ts# Last conversation, scroll position
├── stores/
│   ├── messages-store.ts     # Existing - extend for cached messages
│   ├── session-store.ts      # NEW: Active conversation, scroll pos
│   └── search-store.ts       # NEW: Search state, results
├── hooks/
│   ├── use-message-history.ts    # Pagination hook
│   ├── use-search.ts             # Search hook (local + server)
│   ├── use-session-restore.ts    # Session continuity hook
│   └── use-draft.ts              # Auto-save draft hook
└── components/
    ├── chat/
    │   ├── message-list.tsx      # FlashList with bidirectional scroll
    │   └── search-overlay.tsx    # Search UI with filters
    └── ui/
        └── highlighted-text.tsx  # Search result highlighting

dialectic/
├── api/main.py               # Add search endpoints
└── schema.sql                # Add tsvector column, GIN index
```

### Pattern 1: FlashList with Bidirectional Pagination

**What:** Message list that loads older messages on scroll up, maintains position
**When to use:** Main chat view for all conversations

```typescript
// Source: https://shopify.github.io/flash-list/docs/usage/
// components/chat/message-list.tsx
import { FlashList, FlashListRef } from '@shopify/flash-list';
import { useCallback, useRef, useState } from 'react';

interface MessageListProps {
  threadId: string;
  initialMessages: Message[];
  onLoadOlder: (beforeSequence: number) => Promise<Message[]>;
}

export function MessageList({
  threadId,
  initialMessages,
  onLoadOlder,
}: MessageListProps) {
  const listRef = useRef<FlashListRef<Message>>(null);
  const [messages, setMessages] = useState(initialMessages);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);

  const handleStartReached = useCallback(async () => {
    if (isLoadingOlder || messages.length === 0) return;

    setIsLoadingOlder(true);
    const oldestSequence = messages[0].sequence;

    try {
      const olderMessages = await onLoadOlder(oldestSequence);
      if (olderMessages.length > 0) {
        setMessages((prev) => [...olderMessages, ...prev]);
      }
    } finally {
      setIsLoadingOlder(false);
    }
  }, [isLoadingOlder, messages, onLoadOlder]);

  return (
    <FlashList
      ref={listRef}
      data={messages}
      renderItem={({ item }) => <MessageBubble message={item} />}
      estimatedItemSize={80}
      keyExtractor={(item) => item.id}
      inverted={false} // Chat typically shows newest at bottom
      // FlashList v2: maintainVisibleContentPosition enabled by default
      maintainVisibleContentPosition={{
        autoscrollToTopThreshold: 10, // Auto-scroll if within 10px of top
        autoscrollToBottomThreshold: 100, // Auto-scroll for new messages
      }}
      onStartReached={handleStartReached}
      onStartReachedThreshold={0.5}
      ListHeaderComponent={
        isLoadingOlder ? <LoadingSpinner /> : null
      }
    />
  );
}
```

### Pattern 2: Local Message Cache with Drizzle

**What:** SQLite-backed message cache with 500 message limit per conversation
**When to use:** Offline access, instant loading, reducing server requests

```typescript
// Source: https://orm.drizzle.team/docs/connect-expo-sqlite
// db/schema.ts
import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core';
import { sql } from 'drizzle-orm';

export const cachedMessages = sqliteTable('cached_messages', {
  id: text('id').primaryKey(),
  threadId: text('thread_id').notNull(),
  content: text('content').notNull(),
  senderId: text('sender_id').notNull(),
  senderName: text('sender_name'),
  speakerType: text('speaker_type').notNull(),
  sequence: integer('sequence').notNull(),
  createdAt: text('created_at').notNull(),
  cachedAt: integer('cached_at').notNull(),
});

// Full-text search virtual table
export const messagesSearch = sql`
  CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    sender_name,
    content=cached_messages,
    content_rowid=rowid
  );
`;

// db/index.ts
import { drizzle } from 'drizzle-orm/expo-sqlite';
import { openDatabaseSync } from 'expo-sqlite';
import * as schema from './schema';

const expo = openDatabaseSync('dialectic-cache.db', {
  enableChangeListener: true, // For useLiveQuery
});

export const db = drizzle(expo, { schema });

// services/history/message-cache.ts
import { db } from '@/db';
import { cachedMessages } from '@/db/schema';
import { eq, desc, lt, asc, and, count } from 'drizzle-orm';

const MAX_CACHED_PER_THREAD = 500; // CONTEXT.md requirement

export async function cacheMessages(threadId: string, messages: Message[]) {
  const now = Date.now();

  // Insert new messages
  for (const msg of messages) {
    await db.insert(cachedMessages).values({
      id: msg.id,
      threadId: msg.threadId,
      content: msg.content,
      senderId: msg.senderId,
      senderName: msg.senderName,
      speakerType: msg.speakerType,
      sequence: msg.sequence,
      createdAt: msg.createdAt,
      cachedAt: now,
    }).onConflictDoNothing();
  }

  // Enforce 500 message limit per thread
  await enforceThreadLimit(threadId);
}

async function enforceThreadLimit(threadId: string) {
  const countResult = await db
    .select({ count: count() })
    .from(cachedMessages)
    .where(eq(cachedMessages.threadId, threadId));

  const total = countResult[0]?.count || 0;

  if (total > MAX_CACHED_PER_THREAD) {
    // Delete oldest messages beyond limit
    const toDelete = total - MAX_CACHED_PER_THREAD;
    const oldest = await db
      .select({ id: cachedMessages.id })
      .from(cachedMessages)
      .where(eq(cachedMessages.threadId, threadId))
      .orderBy(asc(cachedMessages.sequence))
      .limit(toDelete);

    for (const row of oldest) {
      await db
        .delete(cachedMessages)
        .where(eq(cachedMessages.id, row.id));
    }
  }
}

export async function getCachedMessages(
  threadId: string,
  limit: number = 50,
  beforeSequence?: number
): Promise<Message[]> {
  let query = db
    .select()
    .from(cachedMessages)
    .where(
      beforeSequence
        ? and(
            eq(cachedMessages.threadId, threadId),
            lt(cachedMessages.sequence, beforeSequence)
          )
        : eq(cachedMessages.threadId, threadId)
    )
    .orderBy(desc(cachedMessages.sequence))
    .limit(limit);

  const rows = await query;
  return rows.reverse().map(rowToMessage);
}

export async function getThreadCacheSize(threadId: string): Promise<number> {
  const result = await db
    .select({ count: count() })
    .from(cachedMessages)
    .where(eq(cachedMessages.threadId, threadId));
  return result[0]?.count || 0;
}
```

### Pattern 3: Session State with MMKV

**What:** Fast storage for session continuity data (last conversation, scroll positions, drafts)
**When to use:** App launch restoration, draft auto-save

```typescript
// Source: https://github.com/mrousavy/react-native-mmkv
// stores/session-store.ts
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { MMKV } from 'react-native-mmkv';

const storage = new MMKV({ id: 'session' });

interface ScrollPosition {
  offset: number;
  messageId?: string; // For jump-to-message
}

interface SessionState {
  // Last active conversation
  lastRoomId: string | null;
  lastThreadId: string | null;

  // Scroll positions per thread
  scrollPositions: Record<string, ScrollPosition>;

  // Drafts per thread
  drafts: Record<string, string>;

  // Actions
  setLastConversation: (roomId: string, threadId: string) => void;
  setScrollPosition: (threadId: string, position: ScrollPosition) => void;
  setDraft: (threadId: string, content: string) => void;
  clearDraft: (threadId: string) => void;
  getDraft: (threadId: string) => string | undefined;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set, get) => ({
      lastRoomId: null,
      lastThreadId: null,
      scrollPositions: {},
      drafts: {},

      setLastConversation: (roomId, threadId) =>
        set({ lastRoomId: roomId, lastThreadId: threadId }),

      setScrollPosition: (threadId, position) =>
        set((state) => ({
          scrollPositions: {
            ...state.scrollPositions,
            [threadId]: position,
          },
        })),

      setDraft: (threadId, content) =>
        set((state) => ({
          drafts: {
            ...state.drafts,
            [threadId]: content,
          },
        })),

      clearDraft: (threadId) =>
        set((state) => {
          const { [threadId]: _, ...rest } = state.drafts;
          return { drafts: rest };
        }),

      getDraft: (threadId) => get().drafts[threadId],
    }),
    {
      name: 'session-storage',
      storage: createJSONStorage(() => ({
        setItem: (name, value) => storage.set(name, value),
        getItem: (name) => storage.getString(name) ?? null,
        removeItem: (name) => storage.delete(name),
      })),
    }
  )
);
```

### Pattern 4: Dual Search (Local + Server)

**What:** Search locally first for instant results, then extend to server
**When to use:** Search within conversation (local) and across all conversations (server)

```typescript
// hooks/use-search.ts
import { useState, useCallback, useMemo } from 'react';
import { searchLocalMessages } from '@/services/history/search-service';
import { api } from '@/services/api';
import { useSessionStore } from '@/stores/session-store';

interface SearchFilters {
  dateFrom?: string;
  dateTo?: string;
  senderType?: 'human' | 'llm';
}

interface SearchResult {
  id: string;
  threadId: string;
  content: string;
  snippet: string; // With highlighted matches
  senderName: string;
  createdAt: string;
  score: number;
}

export function useSearch(currentThreadId: string) {
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<SearchFilters>({});
  const [scope, setScope] = useState<'current' | 'all'>('current');
  const [localResults, setLocalResults] = useState<SearchResult[]>([]);
  const [serverResults, setServerResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const search = useCallback(async (searchQuery: string) => {
    if (!searchQuery.trim()) {
      setLocalResults([]);
      setServerResults([]);
      return;
    }

    setIsSearching(true);
    setQuery(searchQuery);

    try {
      // Always search locally first (instant)
      const local = await searchLocalMessages(
        scope === 'current' ? currentThreadId : undefined,
        searchQuery,
        filters
      );
      setLocalResults(local);

      // If searching all conversations, also hit the server
      if (scope === 'all') {
        const response = await api.get('/messages/search', {
          params: {
            q: searchQuery,
            date_from: filters.dateFrom,
            date_to: filters.dateTo,
            speaker_type: filters.senderType,
            limit: 50,
          },
        });
        setServerResults(response.data);
      }
    } finally {
      setIsSearching(false);
    }
  }, [scope, currentThreadId, filters]);

  // Merge and deduplicate results
  const results = useMemo(() => {
    const seen = new Set<string>();
    const merged: SearchResult[] = [];

    // Local results first (already have them)
    for (const r of localResults) {
      if (!seen.has(r.id)) {
        seen.add(r.id);
        merged.push(r);
      }
    }

    // Then server results (may have additional)
    for (const r of serverResults) {
      if (!seen.has(r.id)) {
        seen.add(r.id);
        merged.push(r);
      }
    }

    // Sort by relevance score
    return merged.sort((a, b) => b.score - a.score);
  }, [localResults, serverResults]);

  return {
    query,
    setQuery,
    filters,
    setFilters,
    scope,
    setScope,
    results,
    isSearching,
    search,
  };
}
```

### Pattern 5: Jump to Message with Context

**What:** Navigate to a search result showing surrounding conversation
**When to use:** Tapping a search result

```typescript
// hooks/use-message-navigation.ts
import { useCallback, useRef } from 'react';
import { FlashListRef } from '@shopify/flash-list';
import { getCachedMessages } from '@/services/history/message-cache';
import { api } from '@/services/api';

interface UseMessageNavigationOptions {
  threadId: string;
  messages: Message[];
  setMessages: (msgs: Message[]) => void;
}

export function useMessageNavigation({
  threadId,
  messages,
  setMessages,
}: UseMessageNavigationOptions) {
  const listRef = useRef<FlashListRef<Message>>(null);

  const navigateToMessage = useCallback(async (messageId: string) => {
    // Check if message is already in view
    const existingIndex = messages.findIndex((m) => m.id === messageId);

    if (existingIndex !== -1) {
      // Message is loaded, just scroll to it
      listRef.current?.scrollToIndex({
        index: existingIndex,
        animated: true,
        viewPosition: 0.5, // Center in view
      });
      return;
    }

    // Message not loaded - need to fetch context around it
    // CONTEXT.md: "Jump + local scroll" pattern
    try {
      // Get message and surrounding context from cache or server
      const contextMessages = await fetchMessageContext(threadId, messageId);

      // Replace current messages with context-centered view
      setMessages(contextMessages);

      // After render, scroll to the target message
      requestAnimationFrame(() => {
        const targetIndex = contextMessages.findIndex((m) => m.id === messageId);
        if (targetIndex !== -1) {
          listRef.current?.scrollToIndex({
            index: targetIndex,
            animated: true,
            viewPosition: 0.5,
          });
        }
      });
    } catch (error) {
      console.error('Failed to navigate to message:', error);
    }
  }, [messages, threadId, setMessages]);

  return { listRef, navigateToMessage };
}

async function fetchMessageContext(
  threadId: string,
  targetMessageId: string,
  contextSize: number = 25 // Messages before and after
): Promise<Message[]> {
  // First try local cache
  // Then fall back to server
  const response = await api.get(`/threads/${threadId}/messages/context`, {
    params: {
      message_id: targetMessageId,
      context: contextSize,
    },
  });
  return response.data;
}
```

### Anti-Patterns to Avoid

- **Loading entire message history at once:** Always paginate; use cursor-based (sequence) not offset-based
- **Using MMKV for large message cache:** MMKV is memory-mapped; use SQLite for 500+ messages
- **ILIKE for server search:** Use GIN-indexed tsvector for O(log n) vs O(n)
- **Polling for new messages:** Use existing WebSocket; only paginate for historical messages
- **Storing scroll offset without message reference:** Offsets change; store messageId + offset for reliability
- **Searching on every keystroke:** Debounce search input (300ms minimum)
- **Ignoring FTS5 for local search:** Basic LIKE queries are slow; FTS5 provides ranking and stemming

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Virtualized bidirectional list | Custom scroll view | FlashList v2 | Handles recycling, position maintenance, performance |
| Local database | Key-value store | expo-sqlite + Drizzle | Type safety, migrations, FTS5 support |
| Full-text search | LIKE '%term%' | FTS5 (local) / GIN (server) | 100x+ faster, ranking, stemming |
| Scroll position maintenance | Manual scroll math | maintainVisibleContentPosition | Battle-tested, handles edge cases |
| Draft auto-save | Manual debounce | Zustand persist + MMKV | Automatic persistence, handles app kills |
| Cache eviction | Manual cleanup | LRU with sequence ordering | Predictable behavior, handles edge cases |

**Key insight:** Chat history has many edge cases (bidirectional loading, position restoration, offline/online transitions, search ranking). Libraries handle these; custom solutions inevitably miss edge cases.

## Common Pitfalls

### Pitfall 1: Scroll Position Lost on Pagination

**What goes wrong:** User scrolls up, older messages load, but scroll jumps to different position
**Why it happens:** Adding items to list without maintaining visual position
**How to avoid:**
- Use FlashList v2 with `maintainVisibleContentPosition` (enabled by default)
- For FlatList, use `react-native-bidirectional-infinite-scroll` wrapper
- Never use offset-based pagination for chat; use cursor (sequence number)
**Warning signs:** Users report "jumping" when scrolling through history

### Pitfall 2: Cache Invalidation on Message Update/Delete

**What goes wrong:** Cached message differs from server truth after edit/delete
**Why it happens:** No mechanism to sync cache with server changes
**How to avoid:**
- On WebSocket reconnect, check for updated messages in gap sync
- Include `updated_at` timestamp in message model
- On conflict, always prefer server version
**Warning signs:** Deleted messages still appear, edited messages show old content

### Pitfall 3: FTS5 Index Out of Sync

**What goes wrong:** Search returns stale or missing results
**Why it happens:** FTS5 contentless tables require manual sync
**How to avoid:**
- Use FTS5 content tables with triggers for auto-sync
- Or use content=table syntax with explicit rebuild on changes
- Test with insert, update, delete operations
**Warning signs:** New messages not searchable, deleted messages still appear in search

### Pitfall 4: Draft Lost on App Kill

**What goes wrong:** User types message, app killed by OS, draft gone
**Why it happens:** Only saving draft on unmount (never called on kill)
**How to avoid:**
- Debounce-save draft on every text change (500ms)
- Use synchronous MMKV write (not async)
- Restore draft on component mount
**Warning signs:** Users report lost messages they were typing

### Pitfall 5: Server Search Timeout on Large History

**What goes wrong:** Search takes 5+ seconds, times out
**Why it happens:** No GIN index, full table scan with ILIKE
**How to avoid:**
- Add tsvector column with GIN index
- Use `to_tsquery` with proper ranking
- Limit results (50 max per query)
- Add created_at index for date filtering
**Warning signs:** Search slow for old conversations, timeouts in production

### Pitfall 6: Memory Pressure from Message Cache

**What goes wrong:** App crashes or slows with large cache
**Why it happens:** Loading all 500 cached messages into memory
**How to avoid:**
- Only load messages needed for current view (50-100)
- Use FlashList's recycling (don't render all items)
- Clear in-memory state on conversation switch
- SQLite handles disk-based storage efficiently
**Warning signs:** Memory warnings, app termination on older devices

### Pitfall 7: Infinite Pagination Loop

**What goes wrong:** App keeps requesting same page of messages
**Why it happens:** Race condition between pagination requests
**How to avoid:**
- Use loading flag to prevent concurrent requests
- Debounce onStartReached/onEndReached callbacks
- Track "no more data" state to stop pagination
- Use unique cursor (sequence) not page number
**Warning signs:** Excessive API calls, duplicate messages appearing

## Code Examples

### Backend: Full-Text Search Endpoint

```python
# Source: PostgreSQL FTS documentation
# Add to dialectic/api/main.py

class SearchMessagesRequest(BaseModel):
    q: str
    thread_id: Optional[UUID] = None  # None = search all
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    speaker_type: Optional[str] = None
    limit: int = 50


class SearchResultResponse(BaseModel):
    id: UUID
    thread_id: UUID
    content: str
    snippet: str
    sender_name: str
    speaker_type: str
    created_at: datetime
    rank: float


@app.get("/messages/search", response_model=List[SearchResultResponse])
async def search_messages(
    q: str,
    token: str = Query(...),
    user_id: UUID = Query(...),
    thread_id: Optional[UUID] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    speaker_type: Optional[str] = None,
    limit: int = 50,
    db=Depends(get_db),
):
    """Full-text search over messages using PostgreSQL tsvector."""
    # Build the search query with GIN index
    query = """
        SELECT
            m.id,
            m.thread_id,
            m.content,
            ts_headline('english', m.content, plainto_tsquery('english', $1),
                'MaxWords=30, MinWords=15, MaxFragments=1') as snippet,
            COALESCE(u.display_name, m.speaker_type) as sender_name,
            m.speaker_type,
            m.created_at,
            ts_rank(m.search_vector, plainto_tsquery('english', $1)) as rank
        FROM messages m
        LEFT JOIN users u ON m.user_id = u.id
        JOIN threads t ON m.thread_id = t.id
        JOIN room_memberships rm ON t.room_id = rm.room_id AND rm.user_id = $2
        WHERE m.search_vector @@ plainto_tsquery('english', $1)
          AND NOT m.is_deleted
    """
    params = [q, user_id]
    param_idx = 3

    if thread_id:
        query += f" AND m.thread_id = ${param_idx}"
        params.append(thread_id)
        param_idx += 1

    if date_from:
        query += f" AND m.created_at >= ${param_idx}"
        params.append(date_from)
        param_idx += 1

    if date_to:
        query += f" AND m.created_at <= ${param_idx}"
        params.append(date_to)
        param_idx += 1

    if speaker_type:
        query += f" AND m.speaker_type = ${param_idx}"
        params.append(speaker_type)
        param_idx += 1

    query += f" ORDER BY rank DESC, m.created_at DESC LIMIT ${param_idx}"
    params.append(limit)

    rows = await db.fetch(query, *params)

    return [SearchResultResponse(
        id=row['id'],
        thread_id=row['thread_id'],
        content=row['content'],
        snippet=row['snippet'],
        sender_name=row['sender_name'],
        speaker_type=row['speaker_type'],
        created_at=row['created_at'],
        rank=row['rank'],
    ) for row in rows]


@app.get("/threads/{thread_id}/messages/context")
async def get_message_context(
    thread_id: UUID,
    message_id: UUID = Query(...),
    context: int = 25,
    token: str = Query(...),
    db=Depends(get_db),
):
    """Get messages around a specific message for jump-to navigation."""
    thread_row = await db.fetchrow(
        "SELECT * FROM threads WHERE id = $1", thread_id
    )
    if not thread_row:
        raise HTTPException(status_code=404, detail="Thread not found")

    await verify_room_token(thread_row['room_id'], token, db)

    # Get the target message's sequence
    target = await db.fetchrow(
        "SELECT sequence FROM messages WHERE id = $1 AND thread_id = $2",
        message_id, thread_id
    )
    if not target:
        raise HTTPException(status_code=404, detail="Message not found")

    target_seq = target['sequence']

    # Get messages around the target
    rows = await db.fetch(
        """SELECT * FROM messages
           WHERE thread_id = $1 AND NOT is_deleted
             AND sequence BETWEEN $2 AND $3
           ORDER BY sequence""",
        thread_id, target_seq - context, target_seq + context
    )

    return [MessageResponse(
        id=row['id'],
        thread_id=row['thread_id'],
        sequence=row['sequence'],
        created_at=row['created_at'],
        speaker_type=row['speaker_type'],
        user_id=row['user_id'],
        message_type=row['message_type'],
        content=row['content'],
    ) for row in rows]
```

### Database Schema Additions

```sql
-- Add to dialectic/schema.sql

-- Full-text search vector column on messages
ALTER TABLE messages ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- Create GIN index for fast text search
CREATE INDEX IF NOT EXISTS idx_messages_search
ON messages USING GIN (search_vector);

-- Trigger to auto-update search vector
CREATE OR REPLACE FUNCTION messages_search_trigger() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('english', COALESCE(NEW.content, ''));
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER messages_search_update
  BEFORE INSERT OR UPDATE ON messages
  FOR EACH ROW EXECUTE FUNCTION messages_search_trigger();

-- Index for date-range queries in search
CREATE INDEX IF NOT EXISTS idx_messages_created_at
ON messages (thread_id, created_at DESC);

-- Backfill existing messages
UPDATE messages SET search_vector = to_tsvector('english', COALESCE(content, ''))
WHERE search_vector IS NULL;
```

### Mobile: SQLite Schema with FTS5

```typescript
// db/migrations/0001_initial.sql
CREATE TABLE IF NOT EXISTS cached_messages (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  content TEXT NOT NULL,
  sender_id TEXT NOT NULL,
  sender_name TEXT,
  speaker_type TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  cached_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cached_messages_thread
ON cached_messages (thread_id, sequence DESC);

CREATE INDEX IF NOT EXISTS idx_cached_messages_cached
ON cached_messages (cached_at ASC);

-- FTS5 for local full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  content,
  sender_name,
  content=cached_messages,
  content_rowid=rowid,
  tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS cached_messages_ai AFTER INSERT ON cached_messages BEGIN
  INSERT INTO messages_fts(rowid, content, sender_name)
  VALUES (NEW.rowid, NEW.content, NEW.sender_name);
END;

CREATE TRIGGER IF NOT EXISTS cached_messages_ad AFTER DELETE ON cached_messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content, sender_name)
  VALUES ('delete', OLD.rowid, OLD.content, OLD.sender_name);
END;

CREATE TRIGGER IF NOT EXISTS cached_messages_au AFTER UPDATE ON cached_messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content, sender_name)
  VALUES ('delete', OLD.rowid, OLD.content, OLD.sender_name);
  INSERT INTO messages_fts(rowid, content, sender_name)
  VALUES (NEW.rowid, NEW.content, NEW.sender_name);
END;

-- Session state table
CREATE TABLE IF NOT EXISTS session_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
```

### Mobile: Local Search Service

```typescript
// services/history/search-service.ts
import { db } from '@/db';
import { sql } from 'drizzle-orm';

interface LocalSearchResult {
  id: string;
  threadId: string;
  content: string;
  snippet: string;
  senderName: string;
  createdAt: string;
  score: number;
}

export async function searchLocalMessages(
  threadId: string | undefined,
  query: string,
  filters: { dateFrom?: string; dateTo?: string; senderType?: string }
): Promise<LocalSearchResult[]> {
  // Use FTS5 for fast local search with ranking
  let ftsQuery = `
    SELECT
      cm.id,
      cm.thread_id as threadId,
      cm.content,
      snippet(messages_fts, 0, '<mark>', '</mark>', '...', 30) as snippet,
      cm.sender_name as senderName,
      cm.created_at as createdAt,
      bm25(messages_fts) as score
    FROM messages_fts
    JOIN cached_messages cm ON messages_fts.rowid = cm.rowid
    WHERE messages_fts MATCH ?
  `;

  const params: any[] = [query];

  if (threadId) {
    ftsQuery += ' AND cm.thread_id = ?';
    params.push(threadId);
  }

  if (filters.dateFrom) {
    ftsQuery += ' AND cm.created_at >= ?';
    params.push(filters.dateFrom);
  }

  if (filters.dateTo) {
    ftsQuery += ' AND cm.created_at <= ?';
    params.push(filters.dateTo);
  }

  if (filters.senderType) {
    ftsQuery += ' AND cm.speaker_type = ?';
    params.push(filters.senderType);
  }

  ftsQuery += ' ORDER BY score LIMIT 50';

  const results = await db.all(sql.raw(ftsQuery), ...params);

  return results as LocalSearchResult[];
}
```

### Mobile: Auto-Save Draft Hook

```typescript
// hooks/use-draft.ts
import { useCallback, useEffect, useRef } from 'react';
import { useSessionStore } from '@/stores/session-store';

const DRAFT_SAVE_DELAY = 500; // ms

export function useDraft(threadId: string) {
  const { getDraft, setDraft, clearDraft } = useSessionStore();
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastSavedRef = useRef<string>('');

  // Restore draft on mount
  const initialDraft = getDraft(threadId) || '';

  const saveDraft = useCallback((content: string) => {
    // Don't save if unchanged
    if (content === lastSavedRef.current) return;

    // Debounce saves
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    timeoutRef.current = setTimeout(() => {
      if (content.trim()) {
        setDraft(threadId, content);
      } else {
        clearDraft(threadId);
      }
      lastSavedRef.current = content;
    }, DRAFT_SAVE_DELAY);
  }, [threadId, setDraft, clearDraft]);

  const discardDraft = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    clearDraft(threadId);
    lastSavedRef.current = '';
  }, [threadId, clearDraft]);

  // Cleanup on unmount
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
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| FlatList for chat | FlashList v2 | 2025 | 10x faster rendering, auto scroll position maintenance |
| AsyncStorage for cache | expo-sqlite | 2024+ | No 6MB limit, proper database features, FTS5 |
| Raw SQL queries | Drizzle ORM | 2024+ | Type safety, migrations, reactive queries |
| ILIKE for search | GIN-indexed tsvector | Standard | O(log n) vs O(n), 100x+ faster for large tables |
| Offset pagination | Cursor pagination | Standard | No skipped/duplicate items, works with mutations |
| Manual scroll restoration | maintainVisibleContentPosition | FlashList v2 | Built-in, handles edge cases |

**Deprecated/outdated:**
- `AsyncStorage` for large data: 6MB limit, use expo-sqlite
- `FlatList` for chat: No automatic scroll position maintenance
- `ILIKE '%term%'` at scale: Full table scan, use proper FTS
- Offset-based pagination: Race conditions with real-time updates

## Open Questions

Things that couldn't be fully resolved:

1. **Exact page size for pagination**
   - What we know: 50 messages is common, CONTEXT.md specifies 50 for initial load
   - What's unclear: Optimal size for "load older" pagination (network vs render tradeoff)
   - Recommendation: Start with 30 for pagination, adjust based on performance testing

2. **Cache eviction timing**
   - What we know: Limit is 500 per thread (CONTEXT.md)
   - What's unclear: When exactly to run eviction (on insert? background task?)
   - Recommendation: Evict on insert to keep logic simple, SQLite handles it efficiently

3. **Search ranking algorithm**
   - What we know: PostgreSQL ts_rank works, FTS5 bm25 works
   - What's unclear: How to weight recency vs relevance
   - Recommendation: Start with default ranking, add `created_at` as tiebreaker

4. **FTS5 tokenizer choice**
   - What we know: 'porter' provides stemming, 'unicode61' handles international text
   - What's unclear: Best tokenizer for chat content with emojis, slang
   - Recommendation: Use 'porter unicode61' combination, test with real data

## Sources

### Primary (HIGH confidence)
- [Expo SQLite Documentation](https://docs.expo.dev/versions/latest/sdk/sqlite/) - Official API reference
- [FlashList Usage](https://shopify.github.io/flash-list/docs/usage/) - Official documentation
- [FlashList v2 Announcement](https://shopify.engineering/flashlist-v2) - New architecture features
- [Drizzle ORM + Expo SQLite](https://orm.drizzle.team/docs/connect-expo-sqlite) - Official integration guide
- [PostgreSQL Text Search](https://www.postgresql.org/docs/current/textsearch-intro.html) - Official documentation
- [PostgreSQL GIN Indexes](https://www.postgresql.org/docs/current/gin.html) - Official documentation

### Secondary (MEDIUM confidence)
- [react-native-bidirectional-infinite-scroll](https://github.com/GetStream/react-native-bidirectional-infinite-scroll) - Stream's production solution
- [react-native-mmkv](https://github.com/mrousavy/react-native-mmkv) - Storage library documentation
- [Building Offline-First Apps](https://medium.com/@detl/building-an-offline-first-production-ready-expo-app-with-drizzle-orm-and-sqlite-f156968547a2) - Implementation patterns
- [pganalyze GIN Index Guide](https://pganalyze.com/blog/gin-index) - Performance considerations

### Tertiary (LOW confidence)
- WebSearch results for chat pagination patterns - Community patterns
- Medium articles on scroll position restoration - Needs validation with FlashList v2

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official Expo packages, well-documented libraries
- Architecture patterns: HIGH - Based on official docs and existing codebase patterns
- Pitfalls: MEDIUM - Combination of docs and community reports
- Backend additions: HIGH - Standard PostgreSQL features

**Research date:** 2026-01-25
**Valid until:** 2026-02-25 (30 days - stable ecosystem)
