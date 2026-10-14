import type { MetadataRoute } from "next";
import { SITE } from "@/content/site";
import { indexable } from "@/lib/page";

export default function robots(): MetadataRoute.Robots {
  // Demo deployments (sample data) and pre-launch synced catalogs stay out of search results.
  if (!indexable()) return { rules: { userAgent: "*", disallow: "/" } };
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/api/", "/en/cart", "/ar/cart", "/en/checkout", "/ar/checkout", "/en/order/", "/ar/order/", "/en/search", "/ar/search"] },
    sitemap: new URL("/sitemap.xml", SITE.url).toString(),
  };
}
