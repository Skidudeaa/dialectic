import SQLite from 'react-native-sqlite-2';
import { Database, DatabaseResult, Transaction } from '@dialectic/app';

const DB_NAME = 'dialectic.db';

/**
 * WebSQL-style types for react-native-sqlite-2.
 * The library doesn't export TypeScript types, so we define them here.
 */
interface SQLResultSet {
  insertId: number;
  rowsAffected: number;
  rows: {
    length: number;
    item(index: number): Record<string, unknown>;
  };
}

interface SQLTransaction {
  executeSql(
    sql: string,
    args?: (string | number)[],
    callback?: (tx: SQLTransaction, result: SQLResultSet) => void,
    errorCallback?: (tx: SQLTransaction, error: Error) => boolean
  ): void;
}

interface SQLiteDatabase {
  transaction(
    callback: (tx: SQLTransaction) => void,
    errorCallback?: (error: Error) => void,
    successCallback?: () => void
  ): void;
  close(): void;
}

/**
 * ARCHITECTURE: react-native-sqlite-2 implementation for Windows.
 * WHY: Same library works on both macOS and Windows platforms.
 * TRADEOFF: WebSQL-style API requires callback wrapping for Promise interface.
 *
 * Note: react-native-sqlite-2 uses the WebSQL API pattern. The Database object
 * returned by openDatabase has transaction() method, not direct execute().
 */
class WindowsDatabase implements Database {
  private db: SQLiteDatabase | null = null;

  private getDb(): SQLiteDatabase {
    if (!this.db) {
      this.db = SQLite.openDatabase(
        DB_NAME,
        '1.0',
        'Dialectic Database',
        5 * 1024 * 1024 // 5MB max size
      ) as unknown as SQLiteDatabase;
    }
    return this.db;
  }

  async execute(sql: string, params: unknown[] = []): Promise<DatabaseResult> {
    return new Promise((resolve, reject) => {
      this.getDb().transaction((tx) => {
        tx.executeSql(
          sql,
          params as (string | number)[],
          (_, result) => {
            resolve({
              insertId: result.insertId,
              rowsAffected: result.rowsAffected,
              rows: Array.from(
                { length: result.rows.length },
                (_, i) => result.rows.item(i)
              ),
            });
          },
          (_, error) => {
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
        async (sqlTx) => {
          const tx: Transaction = {
            execute: (sql, params = []) =>
              new Promise((res, rej) => {
                sqlTx.executeSql(
                  sql,
                  params as (string | number)[],
                  (_, result) =>
                    res({
                      insertId: result.insertId,
                      rowsAffected: result.rowsAffected,
                      rows: Array.from(
                        { length: result.rows.length },
                        (_, i) => result.rows.item(i)
                      ),
                    }),
                  (_, error) => {
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
      this.db.close();
      this.db = null;
    }
  }
}

export const database = new WindowsDatabase();
