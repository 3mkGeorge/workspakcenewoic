import Link from "next/link";

export function Breadcrumbs({ items, label }: { items: { href?: string; label: string }[]; label: string }) {
  return (
    <nav className="breadcrumbs" aria-label={label}>
      <ol>
        {items.map((item, i) => (
          <li key={i}>
            {item.href && i < items.length - 1 ? <Link href={item.href}>{item.label}</Link> : <span aria-current="page">{item.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}
