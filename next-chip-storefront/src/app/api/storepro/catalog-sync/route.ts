import type { NextRequest } from "next/server";
import { json } from "@/lib/api";
import { handleSnapshot } from "@/lib/sync/handlers";
import { guardSignedRequest, maxSnapshotBytes } from "@/lib/sync/request";

/** StorePro pushes catalog snapshots here (HMAC-signed, see STStorePro_INTEGRATION.md). */
export async function POST(request: NextRequest) {
  const guard = await guardSignedRequest(request, { limit: maxSnapshotBytes(), contentTypes: ["application/json"] });
  if (!guard.ok) return guard.response;
  try {
    const r = await handleSnapshot(guard.store, guard.body);
    return json(r.body, r.status);
  } catch (e) {
    console.error("[storepro-sync] snapshot handler error:", e instanceof Error ? e.message : e);
    return json({ error: "server_error" }, 500);
  }
}
