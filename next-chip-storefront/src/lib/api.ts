import "server-only";

import { NextResponse, type NextRequest } from "next/server";
import { ProviderUnavailableError } from "@/lib/commerce/providers";

const MAX_BODY = 16 * 1024;
const NO_STORE = { "Cache-Control": "no-store" };

export const json = (data: unknown, status = 200) => NextResponse.json(data, { status, headers: NO_STORE });

/**
 * Read a small JSON body from a same-origin request. Cross-site posts and
 * non-JSON bodies are refused, so another site can't submit orders on a
 * shopper's behalf.
 */
export async function readJson(request: NextRequest): Promise<{ ok: true; body: unknown } | { ok: false; response: NextResponse }> {
  const origin = request.headers.get("origin");
  if (origin && origin !== request.nextUrl.origin) return { ok: false, response: json({ error: "forbidden" }, 403) };
  if (!(request.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) {
    return { ok: false, response: json({ error: "unsupported_media_type" }, 415) };
  }
  const length = Number(request.headers.get("content-length") ?? 0);
  if (length > MAX_BODY) return { ok: false, response: json({ error: "too_large" }, 413) };
  try {
    const text = await request.text();
    if (text.length > MAX_BODY) return { ok: false, response: json({ error: "too_large" }, 413) };
    return { ok: true, body: JSON.parse(text) as unknown };
  } catch {
    return { ok: false, response: json({ error: "invalid_json" }, 400) };
  }
}

/** Map provider failures to safe responses; never leak internal error text. */
export function failure(error: unknown) {
  if (error instanceof ProviderUnavailableError) return json({ error: "unavailable" }, 503);
  console.error("[storefront api]", error);
  return json({ error: "server_error" }, 500);
}
