import type { NextRequest } from "next/server";
import { getCatalogStore } from "@/lib/catalog-db/server";

const TYPES: Record<string, string> = { jpg: "image/jpeg", png: "image/png", webp: "image/webp" };

/** Public product photos synchronized from StorePro, addressed by content hash (immutable). */
export async function GET(_request: NextRequest, ctx: RouteContext<"/media/[file]">) {
  const { file } = await ctx.params;
  const m = /^([0-9a-f]{64})\.(jpg|png|webp)$/.exec(file);
  if (!m) return new Response("Not found", { status: 404 });
  try {
    const media = await (await getCatalogStore()).getMedia(m[1]!);
    if (!media || media.contentType !== TYPES[m[2]!]) return new Response("Not found", { status: 404 });
    return new Response(Buffer.from(media.bytes), {
      headers: {
        "Content-Type": media.contentType,
        "Content-Length": String(media.bytes.byteLength),
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
      },
    });
  } catch {
    return new Response("Unavailable", { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
