"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

/**
 * Popover behaviour shared by menus and suggestion lists: closes on Escape
 * (returning focus to the trigger), on a pointer press outside, and when
 * focus leaves both the trigger and the panel.
 */
export function useDismiss(
  open: boolean,
  close: (opts?: { restoreFocus?: boolean }) => void,
  refs: RefObject<HTMLElement | null>[],
) {
  useEffect(() => {
    if (!open) return;
    const inside = (node: EventTarget | null) => refs.some((r) => r.current && node instanceof Node && r.current.contains(node));
    const onPointer = (e: PointerEvent) => {
      if (!inside(e.target)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close({ restoreFocus: true });
      }
    };
    const onFocus = (e: FocusEvent) => {
      if (!inside(e.target)) close();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    document.addEventListener("focusin", onFocus);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("focusin", onFocus);
    };
  }, [open, close, refs]);
}

/**
 * Drive a native <dialog> as a modal: focus is trapped by the browser, Escape
 * closes it, a click on the backdrop closes it, and focus returns to whatever
 * opened it.
 */
export function useModal(onClosed?: () => void) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const closedCb = useRef(onClosed);
  useEffect(() => {
    closedCb.current = onClosed;
  }, [onClosed]);

  const show = useCallback(() => {
    const dialog = ref.current;
    if (!dialog || dialog.open) return;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    setOpen(true);
  }, []);

  const hide = useCallback(() => {
    ref.current?.close();
  }, []);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const onClose = () => {
      setOpen(false);
      closedCb.current?.();
      const target = opener.current;
      opener.current = null;
      if (target && target.isConnected) target.focus({ preventScroll: true });
    };
    // A press that starts and ends on the backdrop (outside the dialog box) closes it.
    const onBackdrop = (e: MouseEvent) => {
      if (e.target !== dialog) return false;
      const r = dialog.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    let downOnBackdrop = false;
    const onDown = (e: PointerEvent) => {
      downOnBackdrop = onBackdrop(e);
    };
    const onClick = (e: MouseEvent) => {
      if (downOnBackdrop && onBackdrop(e)) dialog.close();
      downOnBackdrop = false;
    };
    dialog.addEventListener("close", onClose);
    dialog.addEventListener("pointerdown", onDown);
    dialog.addEventListener("click", onClick);
    return () => {
      dialog.removeEventListener("close", onClose);
      dialog.removeEventListener("pointerdown", onDown);
      dialog.removeEventListener("click", onClick);
    };
  }, []);

  // Never leave a modal open across unmounts (e.g. client navigation).
  useEffect(() => {
    const dialog = ref.current;
    return () => dialog?.close();
  }, []);

  return { ref, open, show, hide };
}

/** Debounce a changing value. */
export function useDebounced<T>(value: T, delay: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return v;
}
