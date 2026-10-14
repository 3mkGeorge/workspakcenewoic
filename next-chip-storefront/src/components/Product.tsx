import Image from "next/image";
import Link from "next/link";
import { QuickAdd, WishlistButton } from "@/components/client/product-actions";
import type { Dictionary } from "@/i18n/dictionaries/en";
import { fill, pick } from "@/i18n/format";
import { localePath } from "@/i18n/config";
import { formatEGP } from "@/lib/commerce/money";
import { discountPercent, effectiveSale } from "@/lib/commerce/pricing";
import { safeImageSrc } from "@/lib/commerce/safe-image";
import type { Availability, CatalogItem, Locale, Price as PriceT, ProductImage } from "@/lib/commerce/types";

/** Shared between server pages and client views (wishlist), so no hooks here. */

export function Price({ price, locale, t, size }: { price: PriceT; locale: Locale; t: Dictionary; size?: "lg" }) {
  const sale = effectiveSale(price);
  return (
    <p className={`price${sale.onSale ? " is-sale" : ""}${size === "lg" ? " price-lg" : ""}`}>
      <span className="price-now">
        {sale.onSale && <span className="visually-hidden">{t.product.salePrice}: </span>}
        {formatEGP(sale.amount, locale)}
      </span>
      {sale.onSale && (
        <s className="price-was">
          <span className="visually-hidden">{t.product.regularPrice}: </span>
          {formatEGP(sale.regular, locale)}
        </s>
      )}
    </p>
  );
}

export function StockLabel({ availability, t }: { availability: Availability; t: Dictionary }) {
  switch (availability.status) {
    case "in_stock":
      return (
        <span className="stock stock-in">
          <span className="dot" aria-hidden="true" />
          {t.product.inStock}
        </span>
      );
    case "low_stock":
      return (
        <span className="stock stock-low">
          <span className="dot" aria-hidden="true" />
          {t.product.lowStock}
        </span>
      );
    default:
      return (
        <span className="stock stock-out">
          <span className="dot" aria-hidden="true" />
          {availability.status === "discontinued" ? t.product.unavailable : t.product.outOfStock}
        </span>
      );
  }
}

/** Units a shopper may put in the cart right now (stock and per-order cap). */
export const purchasableQuantity = (item: Pick<CatalogItem, "availability" | "maxPerOrder">) =>
  item.availability.status === "in_stock" || item.availability.status === "low_stock"
    ? Math.max(0, Math.min(item.availability.quantity, item.maxPerOrder))
    : 0;

export function ProductPicture({
  image,
  locale,
  sizes,
  priority = false,
  className,
}: {
  image: ProductImage | undefined;
  locale: Locale;
  sizes: string;
  priority?: boolean;
  className?: string;
}) {
  return (
    <Image
      className={className}
      src={safeImageSrc(image?.src)}
      alt={image ? pick(image.alt, locale) : ""}
      width={image?.width ?? 800}
      height={image?.height ?? 800}
      sizes={sizes}
      priority={priority}
    />
  );
}

export function ProductCard({
  item,
  locale,
  t,
  priority = false,
  headingLevel = 3,
}: {
  item: CatalogItem;
  locale: Locale;
  t: Dictionary;
  priority?: boolean;
  headingLevel?: 2 | 3;
}) {
  const href = localePath(locale, `/products/${item.slug}`);
  const percent = discountPercent(item.price);
  const max = purchasableQuantity(item);
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const name = pick(item.name, locale);
  return (
    <article className="pcard" data-testid="product-card" data-slug={item.slug}>
      <div className="pcard-media">
        <ProductPicture image={item.images[0]} locale={locale} sizes="(min-width: 1200px) 300px, (min-width: 900px) 33vw, 50vw" priority={priority} />
        {percent !== null && (
          <div className="pcard-badges">
            <span className="badge badge-accent">{fill(t.product.save, { percent })}</span>
          </div>
        )}
        <WishlistButton productId={item.id} name={name} className="icon-btn pcard-wish" />
      </div>
      <div className="pcard-body">
        <div className="pcard-info">
          {item.brand && <span className="pcard-brand">{item.brand.name}</span>}
          <Heading className="pcard-title">
            <Link href={href}>{name}</Link>
          </Heading>
          {pick(item.summary, locale) && <p className="pcard-summary">{pick(item.summary, locale)}</p>}
        </div>
        <div className="pcard-foot">
          <div>
            <Price price={item.price} locale={locale} t={t} />
            <StockLabel availability={item.availability} t={t} />
          </div>
          <QuickAdd productId={item.id} name={name} max={max} />
        </div>
      </div>
    </article>
  );
}

export function ProductGrid({
  items,
  locale,
  t,
  view = "grid",
  priorityCount = 0,
  cols4 = false,
  headingLevel = 3,
}: {
  items: CatalogItem[];
  locale: Locale;
  t: Dictionary;
  view?: "grid" | "list";
  priorityCount?: number;
  cols4?: boolean;
  headingLevel?: 2 | 3;
}) {
  return (
    <div className={view === "list" ? "product-list" : `product-grid${cols4 ? " cols-4" : ""}`}>
      {items.map((item, i) => (
        <ProductCard key={item.id} item={item} locale={locale} t={t} priority={i < priorityCount} headingLevel={headingLevel} />
      ))}
    </div>
  );
}
