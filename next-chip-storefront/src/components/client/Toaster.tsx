"use client";

import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { useI18n } from "./I18nProvider";

interface Toast {
  id: number;
  message: string;
  kind: "info" | "error";
  action?: { href: string; label: string };
}
type Notify = (message: string, options?: { kind?: Toast["kind"]; action?: Toast["action"] }) => void;

const Ctx = createContext<Notify>(() => {});
export const useToast = () => useContext(Ctx);

export function Toaster({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setToasts((all) => all.filter((x) => x.id !== id));
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
  }, []);

  const notify = useCallback<Notify>(
    (message, options) => {
      const id = ++seq.current;
      // Keep the stack short: the newest three are enough context.
      setToasts((all) => [...all.slice(-2), { id, message, kind: options?.kind ?? "info", action: options?.action }]);
      timers.current.set(id, setTimeout(() => dismiss(id), options?.kind === "error" ? 7000 : 4500));
    },
    [dismiss],
  );

  useEffect(() => {
    const map = timers.current;
    return () => map.forEach((timer) => clearTimeout(timer));
  }, []);

  return (
    <Ctx.Provider value={notify}>
      {children}
      <div className="toasts" role="status" aria-live="polite" aria-atomic="false">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast${toast.kind === "error" ? " is-error" : ""}`}>
            <Icon name={toast.kind === "error" ? "alert" : "checkCircle"} />
            <span>{toast.message}</span>
            {toast.action && (
              <Link href={toast.action.href} onClick={() => dismiss(toast.id)}>
                {toast.action.label}
              </Link>
            )}
            <button type="button" className="icon-btn" style={{ width: 32, height: 32 }} aria-label={t.common.close} onClick={() => dismiss(toast.id)}>
              <Icon name="close" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
