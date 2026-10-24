import type { NextRequest } from "next/server";
import { json } from "@/lib/api";
import { handleStatus } from "@/lib/sync/handlers";
import { guardSignedRequest } from "@/lib/sync/request";

/** Signed diagnostics for StorePro's Website panel (last applied snapshot, errors, freshness). */
export async function GET(request: NextRequest) {
  const guard = await guardSignedRequest(request, { limit: 0, contentTypes: [] });
  if (!guard.ok) return guard.response;
  const r = await handleStatus(guard.store);
  return json(r.body, r.status);
}
