export const PLACEHOLDER_IMAGE = "/images/placeholder.svg";

/**
 * Hosts allowed for remote product images (e.g. a future StorePro media CDN).
 * Empty in demo mode: every demo image is served from /public.
 */
const ALLOWED_HOSTS = (process.env.NEXT_PUBLIC_IMAGE_HOSTS ?? "")
  .split(",")
  .map((h) => h.trim().toLowerCase())
  .filter(Boolean);

/**
 * Only same-site paths under /images/ or https URLs on allow-listed hosts are
 * rendered; anything else (javascript:, data:, unknown hosts, traversal) falls
 * back to the placeholder.
 */
export function safeImageSrc(src: unknown, allowedHosts: string[] = ALLOWED_HOSTS): string {
  if (typeof src !== "string" || src.length > 500) return PLACEHOLDER_IMAGE;
  if (src.startsWith("/images/") && !src.includes("..") && !src.includes("//") && /^[\w\-./]+$/.test(src)) return src;
  try {
    const url = new URL(src);
    if (url.protocol === "https:" && allowedHosts.includes(url.hostname.toLowerCase())) return url.toString();
  } catch {
    /* not a URL */
  }
  return PLACEHOLDER_IMAGE;
}
