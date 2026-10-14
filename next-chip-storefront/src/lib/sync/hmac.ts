/**
 * Request signing for StorePro → Next Chip calls (format "v1").
 *
 *   canonical = "NEXTCHIP-SYNC-V1\n" + METHOD + "\n" + PATH + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + hex(SHA256(body))
 *   X-NextChip-Signature: v1=hex(HMAC-SHA256(secret, canonical))
 *
 * TIMESTAMP is Unix seconds (X-NextChip-Timestamp), NONCE is 32 lowercase hex
 * characters (X-NextChip-Nonce), PATH is the URL path without query string.
 * The same format is implemented in StorePro's services/web_catalog_sync.py.
 */
import { createHash, createHmac, timingSafeEqual } from "node:crypto";

export const SIGNATURE_PREFIX = "NEXTCHIP-SYNC-V1";
export const MAX_SKEW_SECONDS = 300;
export const MIN_SECRET_LENGTH = 32;
const NONCE = /^[0-9a-f]{32}$/;

export const sha256Hex = (data: Uint8Array | string) => createHash("sha256").update(data).digest("hex");

export function canonicalString(method: string, path: string, timestamp: string, nonce: string, body: Uint8Array | string): string {
  return [SIGNATURE_PREFIX, method.toUpperCase(), path, timestamp, nonce, sha256Hex(body)].join("\n");
}

export function sign(secret: string, method: string, path: string, timestamp: string, nonce: string, body: Uint8Array | string): string {
  return "v1=" + createHmac("sha256", secret).update(canonicalString(method, path, timestamp, nonce, body)).digest("hex");
}

/**
 * Configured secrets: NEXT_CHIP_SYNC_SECRET (current) and, during rotation,
 * NEXT_CHIP_SYNC_SECRET_PREVIOUS. Secrets shorter than 32 characters are ignored.
 */
export function configuredSecrets(env: Record<string, string | undefined> = process.env): string[] {
  return [env.NEXT_CHIP_SYNC_SECRET, env.NEXT_CHIP_SYNC_SECRET_PREVIOUS]
    .map((s) => (s ?? "").trim())
    .filter((s) => s.length >= MIN_SECRET_LENGTH);
}

export type VerifyFailure = "missing_headers" | "bad_timestamp" | "expired" | "bad_nonce" | "bad_signature";

export interface SignedHeaders {
  timestamp: string | null;
  nonce: string | null;
  signature: string | null;
}

/** Check timestamp window and signature. Nonce reuse is checked separately against the database. */
export function verify(
  secrets: string[],
  method: string,
  path: string,
  headers: SignedHeaders,
  body: Uint8Array,
  nowSeconds = Math.floor(Date.now() / 1000),
): { ok: true; nonce: string } | { ok: false; reason: VerifyFailure } {
  const { timestamp, nonce, signature } = headers;
  if (!timestamp || !nonce || !signature) return { ok: false, reason: "missing_headers" };
  if (!/^\d{9,11}$/.test(timestamp)) return { ok: false, reason: "bad_timestamp" };
  if (Math.abs(nowSeconds - Number(timestamp)) > MAX_SKEW_SECONDS) return { ok: false, reason: "expired" };
  if (!NONCE.test(nonce)) return { ok: false, reason: "bad_nonce" };
  if (!/^v1=[0-9a-f]{64}$/.test(signature)) return { ok: false, reason: "bad_signature" };
  const given = Buffer.from(signature);
  for (const secret of secrets) {
    const expected = Buffer.from(sign(secret, method, path, timestamp, nonce, body));
    if (expected.length === given.length && timingSafeEqual(expected, given)) return { ok: true, nonce };
  }
  return { ok: false, reason: "bad_signature" };
}
