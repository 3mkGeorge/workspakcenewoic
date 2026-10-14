import { Breadcrumbs } from "@/components/Breadcrumbs";
import { Icon } from "@/components/Icon";
import type { Dictionary } from "@/i18n/dictionaries/en";
import { pick } from "@/i18n/format";
import { localePath } from "@/i18n/config";
import type { Locale, LocalizedText } from "@/lib/commerce/types";

export function ContentPage({
  locale,
  t,
  title,
  intro,
  draft = false,
  children,
}: {
  locale: Locale;
  t: Dictionary;
  title: string;
  intro?: string;
  draft?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="container">
      <header className="page-head">
        <Breadcrumbs items={[{ href: localePath(locale), label: t.product.home }, { label: title }]} label={t.common.breadcrumbs} />
        <h1>{title}</h1>
        {intro && <p>{intro}</p>}
      </header>
      <div className="content">
        {draft && (
          <div className="alert alert-warning" role="note">
            <Icon name="info" />
            <span>{t.pages.draftNotice}</span>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

/** A configurable business fact, or an explicit "to be confirmed" when Next Chip hasn't provided it. */
export function Configured({ value, locale, t }: { value: LocalizedText | string | null; locale: Locale; t: Dictionary }) {
  if (value === null || value === "") return <em className="pending">{t.pages.policyPending}</em>;
  return <>{typeof value === "string" ? value : pick(value, locale)}</>;
}
