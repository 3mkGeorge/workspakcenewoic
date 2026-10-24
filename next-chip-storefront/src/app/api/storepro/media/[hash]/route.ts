import type { NextRequest } from "next/server";
import { json } from "@/lib/api";
import { handleMediaPut } from "@/lib/sync/handlers";
import { guardSignedRequest, MAX_MEDIA_BYTES } from "@/lib/sync/request";

/** Upload one product image. The URL names the SHA-256 of the exact bytes. */
export async function PUT(request: NextRequest, ctx: RouteContext<"/api/storepro/media/[hash]">) {
  const { hash } = await ctx.params;
  const guard = await guardSignedRequest(request, { limit: MAX_MEDIA_BYTES, contentTypes: ["image/jpeg", "image/png", "image/webp"] });
  if (!guard.ok) return guard.response;
  const type = (request.headers.get("content-type") ?? "").split(";")[0]!.trim().toLowerCase();
  const r = await handleMediaPut(guard.store, hash, type, guard.body);
  return json(r.body, r.status);
}
