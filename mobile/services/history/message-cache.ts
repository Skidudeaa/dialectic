/**
 * ARCHITECTURE: SQLite-backed message cache with eviction.
 * WHY: Enable offline access and instant loading (500 messages per thread).
 * TRADEOFF: Storage space vs unlimited history, but 500 covers most use cases.
 */

import { db, cachedMessages, type CachedMessage } from '@/db';
import { eq, desc, lt, asc, and, count, sql } from 'drizzle-orm';

const MAX_CACHED_PER_THREAD = 500;

export interface CacheableMessage {
  id: string;
  threadId: string;
  content: string;
  senderId: string;
  senderName?: string;
  speakerType: string;
  sequence: number;
  createdAt: string;
}

/**
 * Cache messages to local SQLite database.
 * Enforces 500-message limit per thread by evicting oldest.
 */
export async function cacheMessages(
  threadId: string,
  messages: CacheableMessage[]
): Promise<void> {
  const now = Date.now();

  for (const msg of messages) {
    try {
      await db
        .insert(cachedMessages)
        .values({
          id: msg.id,
          threadId: msg.threadId,
          content: msg.content,
          senderId: msg.senderId,
          senderName: msg.senderName ?? null,
          speakerType: msg.speakerType,
          sequence: msg.sequence,
          createdAt: msg.createdAt,
          cachedAt: now,
        })
        .onConflictDoNothing();
    } catch (error) {
      // Log but don't fail on individual insert errors
      console.warn('[MessageCache] Insert error:', error);
    }
  }

  // Enforce limit after batch insert
  await enforceThreadLimit(threadId);
}

/**
 * Evict oldest messages if thread exceeds 500 message limit.
 */
async function enforceThreadLimit(threadId: string): Promise<void> {
  const countResult = await db
    .select({ count: count() })
    .from(cachedMessages)
    .where(eq(cachedMessages.threadId, threadId));

  const total = countResult[0]?.count ?? 0;

  if (total > MAX_CACHED_PER_THREAD) {
    const toDelete = total - MAX_CACHED_PER_THREAD;

    // Get IDs of oldest messages to delete
    const oldest = await db
      .select({ id: cachedMessages.id })
      .from(cachedMessages)
      .where(eq(cachedMessages.threadId, threadId))
      .orderBy(asc(cachedMessages.sequence))
      .limit(toDelete);

    // Delete them
    for (const row of oldest) {
      await db.delete(cachedMessages).where(eq(cachedMessages.id, row.id));
    }

    console.log(`[MessageCache] Evicted ${toDelete} messages from thread ${threadId}`);
  }
}

/**
 * Get cached messages for a thread with pagination.
 *
 * @param threadId - Thread to get messages for
 * @param limit - Max messages to return
 * @param beforeSequence - Return messages with sequence < this value
 * @returns Messages in ascending sequence order
 */
export async function getCachedMessages(
  threadId: string,
  limit: number = 50,
  beforeSequence?: number
): Promise<CacheableMessage[]> {
  const query = db
    .select()
    .from(cachedMessages)
    .where(
      beforeSequence !== undefined
        ? and(
            eq(cachedMessages.threadId, threadId),
            lt(cachedMessages.sequence, beforeSequence)
          )
        : eq(cachedMessages.threadId, threadId)
    )
    .orderBy(desc(cachedMessages.sequence))
    .limit(limit);

  const rows = await query;

  // Reverse to get ascending order
  return rows.reverse().map((row) => ({
    id: row.id,
    threadId: row.threadId,
    content: row.content,
    senderId: row.senderId,
    senderName: row.senderName ?? undefined,
    speakerType: row.speakerType,
    sequence: row.sequence,
    createdAt: row.createdAt,
  }));
}

/**
 * Get count of cached messages for a thread.
 */
export async function getThreadCacheSize(threadId: string): Promise<number> {
  const result = await db
    .select({ count: count() })
    .from(cachedMessages)
    .where(eq(cachedMessages.threadId, threadId));

  return result[0]?.count ?? 0;
}

/**
 * Get the oldest and newest sequence numbers cached for a thread.
 * Useful for determining if there's a gap to sync.
 */
export async function getCacheSequenceRange(
  threadId: string
): Promise<{ oldest: number | null; newest: number | null }> {
  const result = await db
    .select({
      oldest: sql<number>`MIN(${cachedMessages.sequence})`,
      newest: sql<number>`MAX(${cachedMessages.sequence})`,
    })
    .from(cachedMessages)
    .where(eq(cachedMessages.threadId, threadId));

  return {
    oldest: result[0]?.oldest ?? null,
    newest: result[0]?.newest ?? null,
  };
}

/**
 * Clear cache for a specific thread.
 */
export async function clearThreadCache(threadId: string): Promise<void> {
  await db.delete(cachedMessages).where(eq(cachedMessages.threadId, threadId));
  console.log(`[MessageCache] Cleared cache for thread ${threadId}`);
}
