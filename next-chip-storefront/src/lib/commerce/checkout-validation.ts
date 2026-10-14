import type { CheckoutCustomer, PaymentMethodId } from "./types";

export type FieldError = "required" | "too_short" | "too_long" | "invalid_phone" | "unknown_governorate" | "invalid";
export type CheckoutErrors = Partial<Record<keyof CheckoutCustomer | "paymentMethod" | "lines", FieldError>>;

const ARABIC_DIGITS = /[٠-٩۰-۹]/g;

/** Convert Arabic-Indic digits to Latin and strip spaces, dashes and parentheses. */
export function normalizeDigits(value: string): string {
  return value
    .replace(ARABIC_DIGITS, (d) => String((d.charCodeAt(0) & 0xf) % 10))
    .replace(/[\s\-()]/g, "");
}

/**
 * Egyptian mobile numbers: 11 digits starting 010, 011, 012 or 015. Accepts
 * +20 / 0020 prefixes and Arabic-Indic digits; returns the canonical 01XXXXXXXXX.
 */
export function normalizeEgyptianMobile(value: string): string | null {
  let digits = normalizeDigits(value);
  if (digits.startsWith("+20")) digits = "0" + digits.slice(3);
  else if (digits.startsWith("0020")) digits = "0" + digits.slice(4);
  else if (digits.startsWith("20") && digits.length === 12) digits = "0" + digits.slice(2);
  return /^01[0125]\d{8}$/.test(digits) ? digits : null;
}

const LIMITS: Record<keyof CheckoutCustomer, [number, number]> = {
  name: [3, 80],
  phone: [10, 20],
  governorate: [1, 40],
  city: [2, 60],
  address: [8, 300],
  notes: [0, 500],
};

export function validateCustomer(
  customer: Partial<Record<keyof CheckoutCustomer, unknown>>,
  governorates: string[],
): { errors: CheckoutErrors; value: CheckoutCustomer | null } {
  const errors: CheckoutErrors = {};
  const text = (k: keyof CheckoutCustomer) => (typeof customer[k] === "string" ? (customer[k] as string).trim() : "");
  const value: CheckoutCustomer = {
    name: text("name").replace(/\s+/g, " "),
    phone: text("phone"),
    governorate: text("governorate"),
    city: text("city"),
    address: text("address"),
    notes: text("notes"),
  };
  for (const key of Object.keys(LIMITS) as (keyof CheckoutCustomer)[]) {
    const [min, max] = LIMITS[key];
    const v = value[key];
    if (min > 0 && !v) errors[key] = "required";
    else if (key === "phone") continue; // any non-empty phone is judged by its format below
    else if (v.length < min) errors[key] = "too_short";
    else if (v.length > max) errors[key] = "too_long";
  }
  if (!errors.phone) {
    const phone = normalizeEgyptianMobile(value.phone);
    if (!phone) errors.phone = "invalid_phone";
    else value.phone = phone;
  }
  if (!errors.governorate && !governorates.includes(value.governorate)) errors.governorate = "unknown_governorate";
  return { errors, value: Object.keys(errors).length ? null : value };
}

export function validatePaymentMethod(method: unknown, enabled: PaymentMethodId[]): method is PaymentMethodId {
  return typeof method === "string" && (enabled as string[]).includes(method);
}
