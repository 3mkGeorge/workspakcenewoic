import "@fontsource-variable/inter/wght.css";
import "@/styles/tokens.css";
import "@/styles/base.css";
import "@/styles/components.css";
import "@/styles/pages.css";

import type { Metadata } from "next";

export const metadata: Metadata = { title: "Not found · Next Chip" };

/** Only reached for URLs outside /en and /ar that the proxy does not redirect (e.g. unknown /api paths). */
export default function GlobalNotFound() {
  return (
    <html lang="en" dir="ltr">
      <body>
        <main className="container status-page">
          <div className="empty">
            <span className="code" aria-hidden="true">
              404
            </span>
            <h1 style={{ fontSize: "var(--fs-2xl)" }}>Page not found</h1>
            <p lang="ar" dir="rtl">
              الصفحة غير موجودة
            </p>
            <a className="btn btn-primary" href="/en">
              Back to home
            </a>
          </div>
        </main>
      </body>
    </html>
  );
}
