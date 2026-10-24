/**
 * Apply catalog database migrations: `npm run db:migrate`
 * Reads DATABASE_URL (server-side secret). Safe to run repeatedly.
 */
import pg from "pg";
import { fromPgPool } from "../src/lib/catalog-db/db.ts";
import { expectedSchemaVersion, migrate } from "../src/lib/catalog-db/migrate.ts";

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL is not set. See .env.example.");
  process.exit(1);
}
const pool = new pg.Pool({ connectionString: url, max: 2, ssl: process.env.DATABASE_SSL === "require" ? { rejectUnauthorized: true } : undefined });
const db = fromPgPool(pool);
try {
  const applied = await migrate(db);
  console.log(applied.length ? `Applied migrations: ${applied.join(", ")}` : "Database schema is up to date.");
  console.log(`Schema version: ${expectedSchemaVersion()}`);
} catch (error) {
  console.error("Migration failed:", error instanceof Error ? error.message : error);
  process.exitCode = 1;
} finally {
  await db.close();
}
