"use client";

import Image from "next/image";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Icon } from "@/components/Icon";
import { fill } from "@/i18n/format";
import { useModal } from "@/lib/client/hooks";
import { useI18n } from "./I18nProvider";

export interface GalleryImage {
  src: string;
  alt: string;
  width: number;
  height: number;
}

/** Product gallery: main image, thumbnails, and a full-screen lightbox with zoom. */
export function Gallery({ images, name }: { images: GalleryImage[]; name: string }) {
  const { locale, t } = useI18n();
  const [index, setIndex] = useState(0);
  const [zoom, setZoom] = useState(false);
  const [origin, setOrigin] = useState("50% 50%");
  const { ref, open, show, hide } = useModal(() => setZoom(false));
  const swipe = useRef<{ x: number; y: number } | null>(null);
  const count = images.length;
  const current = images[index] ?? images[0];

  const go = useCallback(
    (delta: number) => {
      setZoom(false);
      setIndex((i) => (i + delta + count) % count);
    },
    [count],
  );

  // Arrow keys follow reading direction: in Arabic, Left means "next".
  const onKey = (e: KeyboardEvent) => {
    const forward = locale === "ar" ? "ArrowLeft" : "ArrowRight";
    const back = locale === "ar" ? "ArrowRight" : "ArrowLeft";
    if (e.key === forward) {
      e.preventDefault();
      go(1);
    } else if (e.key === back) {
      e.preventDefault();
      go(-1);
    }
  };

  const onPointerDown = (e: PointerEvent) => {
    swipe.current = { x: e.clientX, y: e.clientY };
  };
  const onPointerUp = (e: PointerEvent) => {
    const start = swipe.current;
    swipe.current = null;
    if (!start || zoom || count < 2) return;
    const dx = e.clientX - start.x;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(e.clientY - start.y)) {
      const next = dx < 0 ? 1 : -1;
      go(locale === "ar" ? -next : next);
    }
  };
  const toggleZoom = (e?: React.MouseEvent<HTMLElement>) => {
    if (e) {
      const r = e.currentTarget.getBoundingClientRect();
      setOrigin(`${((e.clientX - r.left) / r.width) * 100}% ${((e.clientY - r.top) / r.height) * 100}%`);
    }
    setZoom((z) => !z);
  };
  const pan = (e: React.MouseEvent<HTMLElement>) => {
    if (!zoom) return;
    const r = e.currentTarget.getBoundingClientRect();
    setOrigin(`${((e.clientX - r.left) / r.width) * 100}% ${((e.clientY - r.top) / r.height) * 100}%`);
  };

  useEffect(() => {
    if (index >= count) setIndex(0);
  }, [index, count]);

  if (!current) return null;

  const thumbs = (size: number, label: (i: number) => string) =>
    count > 1 && (
      <ul className="thumbs" aria-label={t.product.gallery}>
        {images.map((img, i) => (
          <li key={img.src}>
            <button type="button" aria-label={label(i)} aria-current={i === index ? "true" : undefined} onClick={() => (setIndex(i), setZoom(false))}>
              <Image src={img.src} alt="" width={size} height={size} sizes={`${size}px`} />
            </button>
          </li>
        ))}
      </ul>
    );

  return (
    <div className="gallery" onKeyDown={onKey}>
      <button type="button" className="gallery-main" onClick={show} aria-label={`${t.product.zoom}: ${current.alt || name}`} aria-haspopup="dialog">
        <Image src={current.src} alt={current.alt || name} width={current.width} height={current.height} sizes="(min-width: 900px) 600px, 100vw" priority />
        <span className="zoom-hint" aria-hidden="true">
          <Icon name="expand" />
          {t.product.zoom}
        </span>
      </button>
      {thumbs(76, (i) => fill(t.product.openImage, { index: i + 1, count }))}
      <p className="demo-render-note">{t.common.demoRender}</p>

      <dialog ref={ref} className="lightbox" aria-label={`${name} — ${t.product.gallery}`}>
        {open && (
          <>
            <div className="lightbox-head">
              <span className="num" aria-live="polite">
                {index + 1} / {count}
              </span>
              <div className="actions">
                <button type="button" className="icon-btn" aria-pressed={zoom} aria-label={zoom ? t.product.zoomOut : t.product.zoomIn} onClick={() => toggleZoom()}>
                  <Icon name={zoom ? "zoomOut" : "zoomIn"} />
                </button>
                <button type="button" className="icon-btn" aria-label={t.common.close} onClick={hide} autoFocus>
                  <Icon name="close" />
                </button>
              </div>
            </div>
            <div className="lightbox-stage">
              <div
                className={`frame${zoom ? " is-zoomed" : ""}`}
                onClick={toggleZoom}
                onMouseMove={pan}
                onPointerDown={onPointerDown}
                onPointerUp={onPointerUp}
              >
                <Image
                  src={current.src}
                  alt={current.alt || name}
                  width={current.width}
                  height={current.height}
                  sizes="100vw"
                  style={{ transform: zoom ? "scale(2.2)" : "none", transformOrigin: origin }}
                  draggable={false}
                />
              </div>
              {count > 1 && (
                <>
                  <button type="button" className="icon-btn lightbox-nav prev" aria-label={t.product.previousImage} onClick={() => go(-1)}>
                    <Icon name="chevronLeft" className="flip-rtl" />
                  </button>
                  <button type="button" className="icon-btn lightbox-nav next" aria-label={t.product.nextImage} onClick={() => go(1)}>
                    <Icon name="chevronRight" className="flip-rtl" />
                  </button>
                </>
              )}
            </div>
            <div className="lightbox-foot">{thumbs(56, (i) => fill(t.product.openImage, { index: i + 1, count }))}</div>
          </>
        )}
      </dialog>
    </div>
  );
}
