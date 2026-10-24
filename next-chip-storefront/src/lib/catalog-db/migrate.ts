/**
 * Forward-only SQL migrations from db/migrations/*.sql, applied in filename
 * order, each in its own transaction, recorded in schema_migrations.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { Db } from "./db.ts";

export const MIGRATIONS_DIR = join(import.meta.dirname ?? __dirname, "..", "..", "..", "db", "migrations");

export function listMigrations(dir = MIGRATIONS_DIR): { version: string; sql: string }[] {
  return readdirSync(dir)
    .filter((f) => /^\d{4}_[a-z0-9_]+\.sql$/.test(f))
    .sort()
    .map((f) => ({ version: f.replace(/\.sql$/, ""), sql: readFileSync(join(dir, f), "utf8") }));
}

export async function migrate(db: Db, dir = MIGRATIONS_DIR): Promise<string[]> {
  await db.query(`CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())`);
  const applied = new Set((await db.query<{ version: string }>("SELECT version FROM schema_migrations")).rows.map((r) => r.version));
  const done: string[] = [];
  for (const m of listMigrations(dir)) {
    if (applied.has(m.version)) continue;
    await db.transaction(async (tx) => {
      // Serialize concurrent runners; the lock is released at transaction end.
      await tx.query("SELECT pg_advisory_xact_lock(727274)");
      const again = await tx.query("SELECT 1 FROM schema_migrations WHERE version = $1", [m.version]);
      if (again.rows.length) return;
      for (const statement of splitSql(m.sql)) await tx.query(statement);
      await tx.query("INSERT INTO schema_migrations (version) VALUES ($1)", [m.version]);
      done.push(m.version);
    });
  }
  return done;
}

/** Latest migration version the code expects. */
export const expectedSchemaVersion = (dir = MIGRATIONS_DIR) => listMigrations(dir).at(-1)?.version ?? null;

/**
 * Split a migration file into statements. Migrations here use no procedural
 * bodies or string literals containing "--" or ";", so stripping line comments
 * and splitting on ";" is exact.
 */
function splitSql(sql: string): string[] {
  return sql
    .replace(/--.*$/gm, "")
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean);
}
