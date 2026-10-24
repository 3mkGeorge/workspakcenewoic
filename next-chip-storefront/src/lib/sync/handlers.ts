import "server-only";

import { contentHash, SyncRejected, type CatalogStore } from "@/lib/catalog-db/store";
import { EXPECTED_SCHEMA_VERSION } from "@/lib/catalog-db/server";
import { isStale, staleAfterMinutes } from "@/lib/freshness";
import { sha256Hex } from "./hmac";
import { validateSnapshot } from "./protocol";
import { logSync } from "./request";

export interface HandlerResult {
  status: number;
  body: Record<string, unknown>;
}

const IMAGE_MAGIC: Record<string, (b: Uint8Array) => boolean> = {
  "image/jpeg": (b) => b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff,
  "image/png": (b) => [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a].every((v, i) => b[i] === v),
  "image/webp": (b) => String.fromCharCode(...b.slice(0, 4)) === "RIFF" && String.fromCharCode(...b.slice(8, 12)) === "WEBP",
};

export async function handleSnapshot(store: CatalogStore, raw: Uint8Array): Promise<HandlerResult> {
  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  } catch {
    await store.recordFailure("Snapshot body was not valid UTF-8 JSON.");
    return { status: 400, body: { error: "invalid_json" } };
  }
  const v = validateSnapshot(payload);
  if (!v.ok) {
    const first = v.issues[0];
    await store.recordFailure(`Snapshot rejected: ${v.issues.length} problem(s); first: ${first?.path} ${first?.message}`);
    logSync("snapshot_invalid", { issues: v.issues.length, first: first?.path });
    return { status: 422, body: { error: "invalid_snapshot", issues: v.issues } };
  }
  const snapshot = v.value;
  try {
    const result = await store.applySnapshot(snapshot);
    logSync("snapshot_" + result.status, {
      snapshot: result.snapshotId,
      complete: snapshot.snapshot.complete,
      products: result.publishedProducts,
      unpublished: result.unpublishedProducts,
      missing_media: result.missingMedia.length,
    });
    return { status: 200, body: { ...result } };
  } catch (e) {
    if (e instanceof SyncRejected) {
      await store.recordFailure(e.message, snapshot, contentHash(snapshot));
      logSync("snapshot_rejected", { snapshot: snapshot.snapshot.id, code: e.code });
      return { status: e.status, body: { error: e.code, message: e.message } };
    }
    // Constraint violations etc.: the transaction rolled back, the last good catalog is untouched.
    const message = e instanceof Error ? e.message : "unknown error";
    await store.recordFailure(`Snapshot could not be applied: ${message}`, snapshot, contentHash(snapshot)).catch(() => {});
    logSync("snapshot_failed", { snapshot: snapshot.snapshot.id, error: message });
    return {
      status: 409,
      body: { error: "apply_failed", message: "The snapshot conflicts with the published catalog and was not applied.", detail: message.slice(0, 200) },
    };
  }
}

export async function handleMediaCheck(store: CatalogStore, raw: Uint8Array): Promise<HandlerResult> {
  let hashes: unknown;
  try {
    hashes = (JSON.parse(new TextDecoder().decode(raw)) as { hashes?: unknown }).hashes;
  } catch {
    return { status: 400, body: { error: "invalid_json" } };
  }
  if (!Array.isArray(hashes) || hashes.length > 5000 || !hashes.every((h) => typeof h === "string" && /^[0-9a-f]{64}$/.test(h))) {
    return { status: 422, body: { error: "invalid_hashes" } };
  }
  return { status: 200, body: { missing: await store.missingMedia(hashes as string[]) } };
}

export async function handleMediaPut(store: CatalogStore, hash: string, contentType: string, bytes: Uint8Array): Promise<HandlerResult> {
  if (!/^[0-9a-f]{64}$/.test(hash)) return { status: 400, body: { error: "invalid_hash" } };
  const check = IMAGE_MAGIC[contentType];
  if (!check) return { status: 415, body: { error: "unsupported_media_type" } };
  if (!bytes.byteLength || sha256Hex(bytes) !== hash) return { status: 422, body: { error: "hash_mismatch" } };
  if (!check(bytes)) return { status: 422, body: { error: "content_type_mismatch" } };
  const result = await store.putMedia(hash, contentType, bytes);
  return { status: result === "stored" ? 201 : 200, body: { status: result } };
}

export async function handleStatus(store: CatalogStore): Promise<HandlerResult> {
  const s = await store.syncState();
  return {
    status: 200,
    body: {
      schemaVersion: EXPECTED_SCHEMA_VERSION,
      ...s,
      stale: isStale(s.lastSuccessAt),
      staleAfterMinutes: staleAfterMinutes(),
      serverTime: new Date().toISOString(),
    },
  };
}
