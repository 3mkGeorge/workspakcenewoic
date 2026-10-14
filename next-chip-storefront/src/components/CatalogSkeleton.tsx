/** Loading placeholder shaped like a catalog page (keeps layout stable while the server renders). */
export function CatalogSkeleton({ withFilters = true }: { withFilters?: boolean }) {
  return (
    <div className="container" aria-busy="true">
      <div className="page-head">
        <div className="skeleton" style={{ height: 14, width: 160 }} />
        <div className="skeleton" style={{ height: 36, width: "min(320px, 70%)", marginTop: "var(--sp-4)" }} />
      </div>
      <div className="catalog">
        {withFilters && (
          <div className="filters-aside">
            <div className="skeleton" style={{ height: 360 }} />
          </div>
        )}
        <div>
          <div className="skeleton" style={{ height: 40, marginBottom: "var(--sp-5)" }} />
          <div className="product-grid">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="skeleton" style={{ aspectRatio: "0.68" }} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
