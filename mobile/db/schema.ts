/**
 * ARCHITECTURE: Drizzle schema for local SQLite message cache.
 * WHY: Type-safe queries with 500-message limit per thread.
 * TRADEOFF: Schema duplication vs server, but needed for offline-first.
 */

import { sqliteTable, text, integer, index } from 'drizzle-orm/sqlite-core';

export const cachedMessages = sqliteTable(
  'cached_messages',
  {
    id: text('id').primaryKey(),
    threadId: text('thread_id').notNull(),
    content: text('content').notNull(),
    senderId: text('sender_id').notNull(),
    senderName: text('sender_name'),
    speakerType: text('speaker_type').notNull(),
    sequence: integer('sequence').notNull(),
    createdAt: text('created_at').notNull(),
    cachedAt: integer('cached_at').notNull(),
  },
  (table) => ({
    threadSeqIdx: index('idx_cached_messages_thread').on(
      table.threadId,
      table.sequence
    ),
    cachedAtIdx: index('idx_cached_messages_cached').on(table.cachedAt),
  })
);

// Type inference for TypeScript
export type CachedMessage = typeof cachedMessages.$inferSelect;
export type NewCachedMessage = typeof cachedMessages.$inferInsert;
