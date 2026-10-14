import type { MetadataRoute } from "next";
import { SITE } from "@/content/site";
import { commerceMode } from "@/lib/commerce";

export default function robots(): MetadataRoute.Robots {
  // Demo deployments show sample products and prices and must stay out of search results.
  if (commerceMode() === "demo") return { rules: { userAgent: "*", disallow: "/" } };
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/api/", "/en/cart", "/ar/cart", "/en/checkout", "/ar/checkout", "/en/order/", "/ar/order/", "/en/search", "/ar/search"] },
    sitemap: new URL("/sitemap.xml", SITE.url).toString(),
  };
}
