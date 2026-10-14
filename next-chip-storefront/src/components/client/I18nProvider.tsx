"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { Dictionary } from "@/i18n/dictionaries/en";
import type { Locale } from "@/lib/commerce/types";

interface I18n {
  locale: Locale;
  t: Dictionary;
}

const Ctx = createContext<I18n | null>(null);

export function I18nProvider({ locale, dict, children }: { locale: Locale; dict: Dictionary; children: ReactNode }) {
  return <Ctx.Provider value={{ locale, t: dict }}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(Ctx);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}
