/** Shared freshness rules for the synchronized catalog. */
export const staleAfterMinutes = (env: Record<string, string | undefined> = process.env) => {
  const n = Number(env.NEXT_CHIP_CATALOG_STALE_MINUTES ?? 120);
  return Number.isFinite(n) && n >= 5 ? Math.floor(n) : 120;
};

export function isStale(lastSuccessAt: string | null, now = Date.now(), minutes = staleAfterMinutes()): boolean {
  if (!lastSuccessAt) return true;
  return now - Date.parse(lastSuccessAt) > minutes * 60_000;
}
