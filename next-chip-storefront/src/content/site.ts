/**
 * Store content that only Next Chip can confirm. Every business fact defaults
 * to null and is shown as "not published yet" / "to be confirmed" until it is
 * filled in here — nothing below is invented on the store's behalf.
 */
import type { LocalizedText } from "@/lib/commerce/types";

export interface SiteContent {
  name: string;
  url: string;
  contact: {
    phone: string | null;
    whatsapp: string | null;
    email: string | null;
    address: LocalizedText | null;
    hours: LocalizedText | null;
  };
  social: { label: string; href: string }[];
  policies: {
    deliveryTime: LocalizedText | null;
    returnWindow: LocalizedText | null;
    returnCondition: LocalizedText | null;
    refundMethod: LocalizedText | null;
    warranty: LocalizedText | null;
    lastReviewed: string | null;
  };
}

export const SITE: SiteContent = {
  name: "Next Chip",
  url: process.env.SITE_URL ?? "http://localhost:3100",
  contact: {
    phone: null,
    whatsapp: null,
    email: null,
    address: null,
    hours: null,
  },
  social: [],
  policies: {
    deliveryTime: null,
    returnWindow: null,
    returnCondition: null,
    refundMethod: null,
    warranty: null,
    lastReviewed: null,
  },
};
