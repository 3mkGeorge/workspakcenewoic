"""Website publication settings per product (web_listings). Opt-in only."""

from models import db, Product, WebListing

LIMITS = {"name_en": 160, "name_ar": 160, "description_en": 4000, "description_ar": 4000}


def ineligibility(product):
    """Why a product marked for the website can't be published right now (None if it can)."""
    if not product.active:
        return "Archived in StorePro"
    if int(product.price or 0) <= 0:
        return "No selling price"
    if product.category is None:
        return "No category"
    if not (product.sku or "").strip():
        return "No SKU"
    return None


def listing_rows():
    """Active products, plus archived ones still marked for the website (so they can be reviewed)."""
    listings = {l.product_id: l for l in WebListing.query.all()}
    products = (
        Product.query.filter(
            (Product.active.is_(True)) | (Product.id.in_([pid for pid, l in listings.items() if l.published]))
        )
        .order_by(Product.name)
        .all()
    )
    rows = []
    for p in products:
        listing = listings.get(p.id)
        images = len(p.images or []) or (1 if p.image else 0)
        rows.append(
            {
                "product": p,
                "listing": listing,
                "published": bool(listing and listing.published),
                "problem": ineligibility(p),
                "images": images,
            }
        )
    return rows


def update_publication(form, actor_audit):
    """Apply the checkbox list from the Website page. Only products shown on that page change."""
    shown = {int(x) for x in form.getlist("product_ids") if str(x).isdigit()}
    wanted = {int(x) for x in form.getlist("published") if str(x).isdigit()} & shown
    if not shown:
        return 0
    existing = {l.product_id: l for l in WebListing.query.filter(WebListing.product_id.in_(shown)).all()}
    valid = {p.id for p in Product.query.filter(Product.id.in_(shown)).all()}
    changed = []
    for pid in sorted(shown & valid):
        listing = existing.get(pid)
        target = pid in wanted
        if listing is None:
            if not target:
                continue
            listing = WebListing(product_id=pid, published=True)
            db.session.add(listing)
            changed.append(f"+{pid}")
        elif listing.published != target:
            listing.published = target
            changed.append(("+" if target else "-") + str(pid))
    if changed:
        actor_audit("Website publication", "Products " + ", ".join(changed[:50]) + (" …" if len(changed) > 50 else ""))
    return len(changed)


def save_listing(product, form, actor_audit):
    """Save web name/description overrides and the per-order limit for one product."""
    listing = product.web_listing or WebListing(product_id=product.id)
    values = {}
    for key, limit in LIMITS.items():
        value = (form.get(key) or "").strip()
        if len(value) > limit:
            raise ValueError(f"Keep {key.replace('_', ' ')} under {limit} characters.")
        values[key] = value
    raw_max = (form.get("max_per_order") or "0").strip() or "0"
    if not raw_max.isdigit() or not 0 <= int(raw_max) <= 99:
        raise ValueError("Per-order limit must be a whole number from 0 to 99 (0 uses the store default).")
    for key, value in values.items():
        setattr(listing, key, value)
    listing.max_per_order = int(raw_max)
    listing.published = form.get("published") == "1"
    if listing not in db.session:
        db.session.add(listing)
    actor_audit("Website listing", f"{product.sku}: {'published' if listing.published else 'not published'}")
    return listing
