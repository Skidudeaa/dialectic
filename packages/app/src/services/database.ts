/**
 * ARCHITECTURE: Platform-agnostic SQLite database interface.
 * WHY: Mobile uses expo-sqlite + Drizzle, desktop may use different SQLite bindings.
 * TRADEOFF: Interface is lower-level than Drizzle ORM; platforms can layer on top.
 *
 * Implementations:
 * - Mobile: expo-sqlite with Drizzle ORM
 * - Desktop: react-native-sqlite-2 with raw SQL (Drizzle may not support)
 */

export interface DatabaseResult {
  insertId?: number;
  rowsAffected: number;
  rows: Record<string, unknown>[];
}

export interface Database {
  /**
   * Execute a SQL statement.
   * @param sql - SQL query string
   * @param params - Query parameters
   */
  execute(sql: string, params?: unknown[]): Promise<DatabaseResult>;

  /**
   * Execute multiple statements in a transaction.
   * @param callback - Function receiving transaction object
   */
  transaction<T>(callback: (tx: Transaction) => Promise<T>): Promise<T>;

  /**
   * Close the database connection.
   */
  close(): Promise<void>;
}

export interface Transaction {
  execute(sql: string, params?: unknown[]): Promise<DatabaseResult>;
}

// Registration pattern (same as secure storage)
let _database: Database | null = null;

export function setDatabaseImplementation(impl: Database): void {
  _database = impl;
}

export function getDatabase(): Database {
  if (!_database) {
    throw new Error('Database not initialized. Call setDatabaseImplementation first.');
  }
  return _database;
}
