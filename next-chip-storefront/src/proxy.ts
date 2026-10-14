import { NextResponse, type NextRequest } from "next/server";

const LOCALES = ["en", "ar"] as const;
const COOKIE = "NEXT_LOCALE";
type Locale = (typeof LOCALES)[number];

const isLocale = (v: string | undefined): v is Locale => v === "en" || v === "ar";

/** Cookie first (explicit choice), then Accept-Language, then English. */
function preferredLocale(request: NextRequest): Locale {
  const cookie = request.cookies.get(COOKIE)?.value;
  if (isLocale(cookie)) return cookie;
  const accept = request.headers.get("accept-language") ?? "";
  const ranked = accept
    .split(",")
    .map((part) => {
      const [tag, q] = part.trim().split(";q=");
      return { lang: (tag ?? "").slice(0, 2).toLowerCase(), q: q ? Number(q) : 1 };
    })
    .filter((x) => x.lang && !Number.isNaN(x.q))
    .sort((a, b) => b.q - a.q);
  const match = ranked.find((x) => isLocale(x.lang));
  return match ? (match.lang as Locale) : "en";
}

/**
 * Every page lives under /en or /ar. Unprefixed paths are redirected to the
 * shopper's language; prefixed paths remember the choice in a cookie.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const first = pathname.split("/")[1];
  if (isLocale(first)) {
    const response = NextResponse.next();
    if (request.cookies.get(COOKIE)?.value !== first) {
      response.cookies.set(COOKIE, first, { path: "/", maxAge: 60 * 60 * 24 * 365, sameSite: "lax" });
    }
    return response;
  }
  const url = request.nextUrl.clone();
  url.pathname = `/${preferredLocale(request)}${pathname === "/" ? "" : pathname}`;
  url.search = search;
  return NextResponse.redirect(url);
}

export const config = {
  // Skip API routes, Next internals and files with an extension (images, icons, robots.txt…).
  matcher: ["/((?!api|_next|images|.*\\..*).*)"],
};
