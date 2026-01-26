/**
 * ARCHITECTURE: SQLite database connection with Drizzle ORM.
 * WHY: Local message cache enables offline access and instant loading.
 * TRADEOFF: Additional storage on device, but enables offline-first UX.
 */

import { drizzle } from 'drizzle-orm/expo-sqlite';
import { openDatabaseSync } from 'expo-sqlite';
import * as schema from './schema';

// Import migration SQL (bundled via babel-plugin-inline-import)
// @ts-ignore - SQL file import
import migration0001 from './migrations/0001_initial.sql';

const DATABASE_NAME = 'dialectic-cache.db';

// Open database synchronously (required by Drizzle)
const expo = openDatabaseSync(DATABASE_NAME);

// Create Drizzle instance with schema
export const db = drizzle(expo, { schema });

// Track migration status
let isMigrated = false;

/**
 * Run database migrations.
 * Call this once on app startup before any queries.
 */
export async function runMigrations(): Promise<void> {
  if (isMigrated) return;

  try {
    // Run migrations using raw SQL
    // Split by semicolons and filter empty statements
    const statements = (migration0001 as string)
      .split(';')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    for (const statement of statements) {
      expo.execSync(statement);
    }

    isMigrated = true;
    console.log('[DB] Migrations complete');
  } catch (error) {
    console.error('[DB] Migration error:', error);
    throw error;
  }
}

/**
 * Get database storage size in bytes.
 * Used for settings screen cache size display.
 */
export async function getDatabaseSize(): Promise<number> {
  try {
    // Query SQLite page_count * page_size
    const result = expo.getFirstSync<{ size: number }>(
      'SELECT (page_count * page_size) as size FROM pragma_page_count(), pragma_page_size()'
    );
    return result?.size ?? 0;
  } catch {
    return 0;
  }
}

/**
 * Clear all cached data (for settings).
 */
export async function clearCache(): Promise<void> {
  expo.execSync('DELETE FROM cached_messages');
  // FTS5 will be cleared by the delete trigger
  console.log('[DB] Cache cleared');
}

// Re-export schema for convenience
export * from './schema';
