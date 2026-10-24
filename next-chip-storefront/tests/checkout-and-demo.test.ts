import { beforeEach, describe, expect, it } from "vitest";
import { normalizeEgyptianMobile, validateCustomer } from "@/lib/commerce/checkout-validation";
import { createDemoCommerce, resetDemoOrders } from "@/lib/commerce/demo/providers";
import { ProviderUnavailableError } from "@/lib/commerce/providers";
import { createStorefrontService } from "@/lib/commerce/service";
import { PLACEHOLDER_IMAGE, safeImageSrc } from "@/lib/commerce/safe-image";

const NOW = new Date("2026-10-14T12:00:00+02:00");
const service = createStorefrontService(createDemoCommerce(), () => NOW);
const GOVS = ["cairo", "giza"];

const customer = { name: "Mona Adel", phone: "0101 234 5678", governorate: "giza", city: "Dokki", address: "12 Example Street, flat 3", notes: "" };
const request = (overrides: Record<string, unknown> = {}) => ({
  customer,
  lines: [{ productId: "p-glidex-control-xl", quantity: 2 }],
  paymentMethod: "cod",
  requestId: "req-0123456789abcdef",
  ...overrides,
});

describe("checkout validation", () => {
  it("accepts Egyptian mobiles in common formats and Arabic digits", () => {
    for (const v of ["01012345678", "+20 101 234 5678", "00201512345678", "٠١٠١٢٣٤٥٦٧٨", "(012) 1234-5678"])
      expect(normalizeEgyptianMobile(v)).toMatch(/^01[0125]\d{8}$/);
    for (const v of ["0131234567", "01312345678", "12345", "0101234567x", "+1 202 555 0100"]) expect(normalizeEgyptianMobile(v)).toBeNull();
  });

  it("reports each missing or invalid field", () => {
    const { errors, value } = validateCustomer({ name: "A", phone: "123", governorate: "mars", city: "", address: "short", notes: "x".repeat(600) }, GOVS);
    expect(value).toBeNull();
    expect(errors).toEqual({ name: "too_short", phone: "invalid_phone", governorate: "unknown_governorate", city: "required", address: "too_short", notes: "too_long" });
  });

  it("normalizes a valid customer", () => {
    const { errors, value } = validateCustomer({ ...customer, name: "  Mona   Adel " }, GOVS);
    expect(errors).toEqual({});
    expect(value).toMatchObject({ name: "Mona Adel", phone: "01012345678" });
  });
});

describe("demo checkout", () => {
  beforeEach(() => resetDemoOrders());

  it("creates a demo order with server-computed totals, ignoring client prices", async () => {
    const r = await service.placeOrder(request({ total: 1, lines: [{ productId: "p-glidex-control-xl", quantity: 2, unitPrice: 1 }] }));
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.order).toMatchObject({ status: "demo", demo: true, paymentMethod: "cod" });
    expect(r.order.id).toMatch(/^DEMO-\d+-[0-9a-f]{8}$/);
    expect(r.order.totals).toEqual({ subtotal: 239800, discount: 0, shipping: 6000, total: 245800, itemCount: 2 });
    expect(await service.getOrder(r.order.id)).toMatchObject({ id: r.order.id, demo: true });
  });

  it("is idempotent on requestId (double submit = one order)", async () => {
    const a = await service.placeOrder(request());
    const b = await service.placeOrder(request());
    expect(a.ok && b.ok && a.order.id === b.order.id).toBe(true);
  });

  it("rejects invalid input, disabled payment methods and unpurchasable carts", async () => {
    const bad = await service.placeOrder(request({ customer: { ...customer, phone: "123" }, paymentMethod: "card" }));
    expect(bad).toMatchObject({ ok: false, reason: "invalid", errors: { phone: "invalid_phone", paymentMethod: "invalid" } });
    const empty = await service.placeOrder(request({ lines: [] }));
    expect(empty).toMatchObject({ ok: false, reason: "invalid", errors: { lines: "required" } });
    const soldOut = await service.placeOrder(request({ lines: [{ productId: "p-nexa-wraith-mini", quantity: 1 }] }));
    expect(soldOut).toMatchObject({ ok: false, reason: "cart" });
    const tooMany = await service.placeOrder(request({ lines: [{ productId: "p-kinetiq-mag60-he", quantity: 4 }] }));
    expect(tooMany).toMatchObject({ ok: false, reason: "cart" });
  });

  it("only offers enabled payment methods (cash on delivery in demo)", async () => {
    expect((await service.listPaymentMethods()).map((m) => m.id)).toEqual(["cod"]);
  });
});

describe("demo mode honesty and provider boundary", () => {

  it("home data only includes valid promotions and real sections", async () => {
    const home = await service.getHome();
    expect(home.promotions.map((p) => p.id)).toEqual(["promo-aim-season"]);
    expect(home.categories.map((c) => c.slug)).toEqual([
      "gaming-mice", "mousepads", "mouse-skates", "keyboards", "headsets-iems", "microphones", "cables-accessories",
    ]);
    expect(home.categories.every((c) => c.count > 0)).toBe(true);
    expect(home.bestSellers[0]?.slug).toBe("vortek-v1-air");
  });

  it("product detail hides discontinued products and returns related items", async () => {
    expect(await service.getProduct("vortek-legacy-g1")).toBeNull();
    const detail = await service.getProduct("vortek-v1-air");
    expect(detail?.related.length).toBeGreaterThan(0);
    expect(detail?.related.every((r) => r.id !== detail.item.id)).toBe(true);
  });
});

describe("image URL safety", () => {
  it("allows local images and allow-listed https hosts only", () => {
    expect(safeImageSrc("/images/products/x-1.svg")).toBe("/images/products/x-1.svg");
    expect(safeImageSrc("https://cdn.example.com/a.png", ["cdn.example.com"])).toBe("https://cdn.example.com/a.png");
    for (const bad of ["javascript:alert(1)", "data:image/svg+xml,<svg/>", "/images/../secrets", "//evil.com/x.png", "http://cdn.example.com/a.png", "https://evil.com/a.png", 42, null])
      expect(safeImageSrc(bad, ["cdn.example.com"])).toBe(PLACEHOLDER_IMAGE);
  });
});
