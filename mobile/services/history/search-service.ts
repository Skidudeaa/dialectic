/**
 * ARCHITECTURE: FTS5-powered local search for instant results.
 * WHY: Search cached messages without network latency.
 * TRADEOFF: Only searches cached messages, server extends to full history.
 */

import { openDatabaseSync } from 'expo-sqlite';

// Use the same database name as db/index.ts
const DATABASE_NAME = 'dialectic-cache.db';
const expo = openDatabaseSync(DATABASE_NAME);

export interface LocalSearchResult {
  id: string;
  threadId: string;
  content: string;
  snippet: string;
  senderName: string;
  speakerType: string;
  createdAt: string;
  score: number;
}

export interface SearchFilters {
  dateFrom?: string; // ISO date string
  dateTo?: string;   // ISO date string
  senderType?: 'human' | 'llm';
}

/**
 * Search local cached messages using FTS5.
 *
 * @param threadId - Optional thread to search within (null = all threads)
 * @param query - Search query string
 * @param filters - Optional filters for date range and sender type
 * @returns Search results with snippets and scores
 */
export async function searchLocalMessages(
  threadId: string | null,
  query: string,
  filters: SearchFilters = {}
): Promise<LocalSearchResult[]> {
  if (!query.trim()) return [];

  // Build the FTS5 query
  // Using bm25() for relevance scoring and snippet() for highlighted excerpts
  let ftsQuery = `
    SELECT
      cm.id,
      cm.thread_id as threadId,
      cm.content,
      snippet(messages_fts, 0, '<mark>', '</mark>', '...', 30) as snippet,
      COALESCE(cm.sender_name, cm.speaker_type) as senderName,
      cm.speaker_type as speakerType,
      cm.created_at as createdAt,
      bm25(messages_fts) as score
    FROM messages_fts
    JOIN cached_messages cm ON messages_fts.rowid = cm.rowid
    WHERE messages_fts MATCH ?
  `;

  const params: (string | number)[] = [query];

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
    if (filters.senderType === 'llm') {
      ftsQuery += " AND cm.speaker_type IN ('LLM_PRIMARY', 'LLM_PROVOKER')";
    } else {
      ftsQuery += " AND cm.speaker_type = 'HUMAN'";
    }
  }

  ftsQuery += ' ORDER BY score LIMIT 50';

  try {
    // Use expo-sqlite's getAllSync for raw queries
    // This is the correct method for Expo SQLite, NOT db.all()
    const results = expo.getAllSync<LocalSearchResult>(ftsQuery, params);
    return results;
  } catch (error) {
    console.error('[LocalSearch] FTS5 query error:', error);
    return [];
  }
}
