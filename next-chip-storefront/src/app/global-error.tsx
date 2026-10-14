"use client";

/** Last-resort error screen when the root layout itself fails. Plain styles: global CSS isn't loaded here. */
export default function GlobalError({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, minHeight: "100vh", display: "grid", placeItems: "center", background: "#0a0b0d", color: "#f1f4f6", fontFamily: "system-ui, sans-serif" }}>
        <title>Something went wrong · Next Chip</title>
        <div style={{ textAlign: "center", padding: 24 }}>
          <h1 style={{ fontSize: 28, margin: "0 0 8px" }}>Something went wrong</h1>
          <p style={{ color: "#8a94a0", margin: "0 0 4px" }}>The store couldn&apos;t load. Please try again.</p>
          <p dir="rtl" lang="ar" style={{ color: "#8a94a0", margin: "0 0 20px" }}>
            حدث خطأ أثناء تحميل المتجر. حاول مرة أخرى.
          </p>
          <button
            type="button"
            onClick={() => retry()}
            style={{ minHeight: 44, padding: "0 20px", border: 0, borderRadius: 12, background: "#b8f53b", color: "#0a0b0d", fontWeight: 600, cursor: "pointer" }}
          >
            Try again · حاول مرة أخرى
          </button>
        </div>
      </body>
    </html>
  );
}
