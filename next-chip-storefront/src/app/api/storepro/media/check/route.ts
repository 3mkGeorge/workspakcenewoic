import type { NextRequest } from "next/server";
import { json } from "@/lib/api";
import { handleMediaCheck } from "@/lib/sync/handlers";
import { guardSignedRequest } from "@/lib/sync/request";

/** Which of these image hashes still need uploading? */
export async function POST(request: NextRequest) {
  const guard = await guardSignedRequest(request, { limit: 512 * 1024, contentTypes: ["application/json"] });
  if (!guard.ok) return guard.response;
  const r = await handleMediaCheck(guard.store, guard.body);
  return json(r.body, r.status);
}
