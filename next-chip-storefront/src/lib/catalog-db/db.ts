/**
 * Minimal database interface shared by the production PostgreSQL pool and the
 * in-process PGlite used by tests. Plain TypeScript (no path aliases) so the
 * migration CLI can run it with Node's built-in type stripping.
 */
import type { Pool, PoolClient } from "pg";

export interface QueryResult<T> {
  rows: T[];
}

export interface Queryable {
  query<T = Record<string, unknown>>(sql: string, params?: unknown[]): Promise<QueryResult<T>>;
}

export interface Db extends Queryable {
  /** Run `fn` in one transaction: COMMIT on success, ROLLBACK on any error. */
  transaction<T>(fn: (tx: Queryable) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}

export function fromPgPool(pool: Pool): Db {
  return {
    query: async <T>(sql: string, params: unknown[] = []) => {
      const r = await pool.query(sql, params);
      return { rows: r.rows as T[] };
    },
    async transaction<T>(fn: (tx: Queryable) => Promise<T>): Promise<T> {
      const client: PoolClient = await pool.connect();
      try {
        await client.query("BEGIN");
        const tx: Queryable = {
          query: async <R>(sql: string, params: unknown[] = []) => ({ rows: (await client.query(sql, params)).rows as R[] }),
        };
        const result = await fn(tx);
        await client.query("COMMIT");
        return result;
      } catch (error) {
        await client.query("ROLLBACK").catch(() => {});
        throw error;
      } finally {
        client.release();
      }
    },
    close: () => pool.end(),
  };
}

/** Structural type of the PGlite instance methods we use (avoids a runtime dependency). */
export interface PGliteLike {
  query<T>(sql: string, params?: unknown[]): Promise<{ rows: T[] }>;
  exec(sql: string): Promise<unknown>;
  transaction<T>(fn: (tx: { query<R>(sql: string, params?: unknown[]): Promise<{ rows: R[] }> }) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}

export function fromPGlite(pg: PGliteLike): Db {
  return {
    query: async <T>(sql: string, params: unknown[] = []) => ({ rows: (await pg.query<T>(sql, params)).rows }),
    transaction: <T>(fn: (tx: Queryable) => Promise<T>) =>
      pg.transaction((tx) => fn({ query: async <R>(sql: string, params: unknown[] = []) => ({ rows: (await tx.query<R>(sql, params)).rows }) })),
    close: () => pg.close(),
  };
}
