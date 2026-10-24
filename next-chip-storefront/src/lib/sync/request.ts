import "server-only";

import type { NextRequest, NextResponse } from "next/server";
import { json } from "@/lib/api";
import { getCatalogStore } from "@/lib/catalog-db/server";
import type { CatalogStore } from "@/lib/catalog-db/store";
import { configuredSecrets, verify } from "./hmac";

/** Snapshot bodies: ~8 MB covers tens of thousands of products. Override with NEXT_CHIP_SYNC_MAX_BYTES. */
export const maxSnapshotBytes = () => {
  const n = Number(process.env.NEXT_CHIP_SYNC_MAX_BYTES ?? 8 * 1024 * 1024);
  return Number.isFinite(n) && n > 0 ? Math.min(n, 64 * 1024 * 1024) : 8 * 1024 * 1024;
};
export const MAX_MEDIA_BYTES = 5 * 1024 * 1024;

/** Log a sync event without secrets, signatures or payload contents. */
export function logSync(event: string, details: Record<string, string | number | boolean | null | undefined> = {}) {
  const parts = Object.entries(details)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${k}=${String(v).slice(0, 120)}`);
  console.info(`[storepro-sync] ${event}${parts.length ? " " + parts.join(" ") : ""}`);
}

/** Read the body while enforcing a byte limit (Content-Length can be absent or wrong). */
export async function readLimited(request: NextRequest, limit: number): Promise<Uint8Array | null> {
  const declared = Number(request.headers.get("content-length") ?? NaN);
  if (Number.isFinite(declared) && declared > limit) return null;
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(size);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.byteLength;
  }
  return out;
}

export type Guarded = { ok: true; body: Uint8Array; store: CatalogStore } | { ok: false; response: NextResponse };

/**
 * Authenticate a StorePro request: configured secret, size limit, HMAC
 * signature over method/path/timestamp/nonce/body, timestamp window, and a
 * single-use nonce. Only then is the catalog database touched for writes.
 */
export async function guardSignedRequest(
  request: NextRequest,
  opts: { limit: number; contentTypes: string[] },
): Promise<Guarded> {
  const path = request.nextUrl.pathname;
  const secrets = configuredSecrets();
  if (!secrets.length) {
    logSync("rejected", { path, reason: "not_configured" });
    return { ok: false, response: json({ error: "sync_not_configured" }, 503) };
  }
  const type = (request.headers.get("content-type") ?? "").split(";")[0]!.trim().toLowerCase();
  if (opts.contentTypes.length && !opts.contentTypes.includes(type)) {
    return { ok: false, response: json({ error: "unsupported_media_type" }, 415) };
  }
  const body = await readLimited(request, opts.limit);
  if (!body) {
    logSync("rejected", { path, reason: "too_large" });
    return { ok: false, response: json({ error: "too_large", limit: opts.limit }, 413) };
  }
  const result = verify(
    secrets,
    request.method,
    path,
    {
      timestamp: request.headers.get("x-nextchip-timestamp"),
      nonce: request.headers.get("x-nextchip-nonce"),
      signature: request.headers.get("x-nextchip-signature"),
    },
    body,
  );
  if (!result.ok) {
    logSync("rejected", { path, reason: result.reason });
    // Same answer for every authentication failure; the reason stays in the server log.
    return { ok: false, response: json({ error: result.reason === "expired" ? "expired" : "unauthorized" }, 401) };
  }
  let store: CatalogStore;
  try {
    store = await getCatalogStore();
  } catch (e) {
    logSync("rejected", { path, reason: "database_unavailable" });
    return { ok: false, response: json({ error: "database_unavailable" }, 503) };
  }
  if (!(await store.useNonce(result.nonce))) {
    logSync("rejected", { path, reason: "replay" });
    return { ok: false, response: json({ error: "replay" }, 409) };
  }
  return { ok: true, body, store };
}
