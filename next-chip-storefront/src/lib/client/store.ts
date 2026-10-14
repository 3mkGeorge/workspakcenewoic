"use client";
/**
 * Browser-side shopping state: cart lines (ids + quantities only), wishlist,
 * the shopper's governorate and references to demo orders placed from this
 * browser. Persisted in localStorage and synced across tabs. Prices are never
 * stored here — they always come from the server.
 */
import { useSyncExternalStore } from "react";

export interface CartEntry {
  productId: string;
  quantity: number;
}
export interface OrderRef {
  id: string;
  createdAt: string;
  total: number;
  itemCount: number;
  demo: boolean;
}
export interface StoreState {
  ready: boolean;
  cart: CartEntry[];
  wishlist: string[];
  orders: OrderRef[];
  governorate: string | null;
}

const KEY = "nextchip:store:v1";
export const MAX_LINES = 50;
export const MAX_QTY = 99;
const ID = /^[a-z0-9-]{1,64}$/;

const SERVER: StoreState = { ready: false, cart: [], wishlist: [], orders: [], governorate: null };
let state: StoreState | null = null;
const listeners = new Set<() => void>();

function sanitize(raw: unknown): StoreState {
  const o = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const cart = (Array.isArray(o.cart) ? o.cart : [])
    .filter(
      (l): l is CartEntry =>
        !!l &&
        typeof l === "object" &&
        typeof (l as CartEntry).productId === "string" &&
        ID.test((l as CartEntry).productId) &&
        Number.isInteger((l as CartEntry).quantity) &&
        (l as CartEntry).quantity > 0,
    )
    .slice(0, MAX_LINES)
    .map((l) => ({ productId: l.productId, quantity: Math.min(MAX_QTY, l.quantity) }));
  const wishlist = [...new Set((Array.isArray(o.wishlist) ? o.wishlist : []).filter((id): id is string => typeof id === "string" && ID.test(id)))].slice(0, 100);
  const orders = (Array.isArray(o.orders) ? o.orders : [])
    .filter(
      (r): r is OrderRef =>
        !!r && typeof r === "object" && typeof (r as OrderRef).id === "string" && /^[A-Za-z0-9-]{1,40}$/.test((r as OrderRef).id),
    )
    .slice(0, 20)
    .map((r) => ({
      id: r.id,
      createdAt: typeof r.createdAt === "string" ? r.createdAt : "",
      total: Number.isSafeInteger(r.total) ? r.total : 0,
      itemCount: Number.isSafeInteger(r.itemCount) ? r.itemCount : 0,
      demo: r.demo !== false,
    }));
  const governorate = typeof o.governorate === "string" && ID.test(o.governorate) ? o.governorate : null;
  return { ready: true, cart, wishlist, orders, governorate };
}

function load(): StoreState {
  try {
    return sanitize(JSON.parse(window.localStorage.getItem(KEY) ?? "null"));
  } catch {
    return sanitize(null);
  }
}

function current(): StoreState {
  if (!state) state = load();
  return state;
}

function commit(next: Omit<StoreState, "ready">) {
  state = { ...next, ready: true };
  try {
    const { ready: _ready, ...persisted } = state;
    window.localStorage.setItem(KEY, JSON.stringify(persisted));
  } catch {
    /* storage full or disabled: keep working in memory */
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY || e.key === null) {
      state = load();
      listeners.forEach((l) => l());
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useStore(): StoreState {
  return useSyncExternalStore(subscribe, current, () => SERVER);
}

export const cartCount = (s: StoreState) => s.cart.reduce((n, l) => n + l.quantity, 0);

/** Current quantity of a product in the cart, for use inside event handlers. */
export const quantityInCart = (productId: string) => current().cart.find((l) => l.productId === productId)?.quantity ?? 0;

/**
 * Add `quantity` of a product, never exceeding `max` (stock and per-order cap
 * as last seen). Returns how many units the line holds afterwards and whether
 * the request was capped. The server re-checks everything at quote time.
 */
export function addToCart(productId: string, quantity: number, max: number): { quantity: number; capped: boolean } {
  const s = current();
  const limit = Math.max(0, Math.min(MAX_QTY, Math.floor(max)));
  const existing = s.cart.find((l) => l.productId === productId);
  const wanted = (existing?.quantity ?? 0) + Math.max(1, Math.floor(quantity));
  const next = Math.min(wanted, limit);
  if (next <= 0) return { quantity: existing?.quantity ?? 0, capped: true };
  if (!existing && s.cart.length >= MAX_LINES) return { quantity: 0, capped: true };
  const cart = existing
    ? s.cart.map((l) => (l.productId === productId ? { ...l, quantity: next } : l))
    : [...s.cart, { productId, quantity: next }];
  commit({ ...s, cart });
  return { quantity: next, capped: next < wanted };
}

export function setQuantity(productId: string, quantity: number) {
  const s = current();
  const q = Math.min(MAX_QTY, Math.floor(quantity));
  if (!Number.isFinite(q)) return;
  if (q < 1) return removeFromCart(productId);
  commit({ ...s, cart: s.cart.map((l) => (l.productId === productId ? { ...l, quantity: q } : l)) });
}

export function removeFromCart(productId: string) {
  const s = current();
  commit({ ...s, cart: s.cart.filter((l) => l.productId !== productId) });
}

export function clearCart() {
  commit({ ...current(), cart: [] });
}

/** Returns true when the product is in the wishlist afterwards. */
export function toggleWishlist(productId: string): boolean {
  const s = current();
  const has = s.wishlist.includes(productId);
  commit({ ...s, wishlist: has ? s.wishlist.filter((id) => id !== productId) : [productId, ...s.wishlist].slice(0, 100) });
  return !has;
}

export function rememberOrder(ref: OrderRef) {
  const s = current();
  commit({ ...s, orders: [ref, ...s.orders.filter((o) => o.id !== ref.id)].slice(0, 20) });
}

export function setGovernorate(id: string | null) {
  const s = current();
  if (s.governorate === id) return;
  commit({ ...s, governorate: id && ID.test(id) ? id : null });
}
