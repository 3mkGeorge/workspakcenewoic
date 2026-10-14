import type { Locale } from "@/lib/commerce/types";
import ar from "./dictionaries/ar";
import en, { type Dictionary } from "./dictionaries/en";

const DICTIONARIES: Record<Locale, Dictionary> = { en, ar };

export const getDictionary = (locale: Locale): Dictionary => DICTIONARIES[locale];
export type { Dictionary };
export { fill, pick } from "./format";
