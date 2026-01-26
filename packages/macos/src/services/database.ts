/**
 * macOS SQLite database implementation.
 *
 * ARCHITECTURE: Uses react-native-sqlite-2 with WebSQL-style API.
 * WHY: expo-sqlite not available in bare workflow; this provides SQLite access.
 * TRADEOFF: WebSQL API is async-callback based, different from Drizzle ORM.
 */

import SQLite, {
  type WebsqlDatabase,
  type SQLTransaction,
  type SQLResultSet,
  type SQLError,
} from 'react-native-sqlite-2';
import type { Database, DatabaseResult, Transaction } from '@dialectic/app';

const DB_NAME = 'dialectic.db';

/**
 * react-native-sqlite-2 implementation for macOS.
 *
 * Note: This uses WebSQL-style API, not expo-sqlite's synchronous API.
 * Drizzle ORM may not work directly - use raw SQL queries.
 */
class MacOSDatabase implements Database {
  private db: WebsqlDatabase | null = null;

  private getDb(): WebsqlDatabase {
    if (!this.db) {
      this.db = SQLite.openDatabase(
        DB_NAME,
        '1.0',
        'Dialectic Database',
        5 * 1024 * 1024
      );
    }
    return this.db;
  }

  async execute(sql: string, params: unknown[] = []): Promise<DatabaseResult> {
    return new Promise((resolve, reject) => {
      this.getDb().transaction((tx: SQLTransaction) => {
        tx.executeSql(
          sql,
          params as (string | number)[],
          (_tx: SQLTransaction, result: SQLResultSet) => {
            resolve({
              insertId: result.insertId,
              rowsAffected: result.rowsAffected,
              rows: Array.from({ length: result.rows.length }, (_, i) =>
                result.rows.item(i)
              ),
            });
          },
          (_tx: SQLTransaction, error: SQLError) => {
            reject(error);
            return false;
          }
        );
      });
    });
  }

  async transaction<T>(callback: (tx: Transaction) => Promise<T>): Promise<T> {
    return new Promise((resolve, reject) => {
      this.getDb().transaction(
        async (sqlTx: SQLTransaction) => {
          const tx: Transaction = {
            execute: (sql, params = []) =>
              new Promise((res, rej) => {
                sqlTx.executeSql(
                  sql,
                  params as (string | number)[],
                  (_tx: SQLTransaction, result: SQLResultSet) =>
                    res({
                      insertId: result.insertId,
                      rowsAffected: result.rowsAffected,
                      rows: Array.from({ length: result.rows.length }, (_, i) =>
                        result.rows.item(i)
                      ),
                    }),
                  (_tx: SQLTransaction, error: SQLError) => {
                    rej(error);
                    return false;
                  }
                );
              }),
          };
          try {
            const result = await callback(tx);
            resolve(result);
          } catch (e) {
            reject(e);
          }
        },
        reject
      );
    });
  }

  async close(): Promise<void> {
    if (this.db) {
      // WebsqlDatabase doesn't have a close method in the interface
      // but the underlying implementation may support it
      (this.db as unknown as { close?: () => void }).close?.();
      this.db = null;
    }
  }
}

export const database = new MacOSDatabase();
