"""Inventory operations and stock adjustment domain service for StorePro.

Extracts inventory movements, stock adjustments, underflow guards with
administrative override, and adjustment history queries from routes.
"""

from flask import url_for
from models import db, Product, InventoryMovement, User
from services.core import integer, required, move, audit
from services.analytics import stock_stats, bounds, local_today

ADJUST_TYPES = (
    "Add Stock",
    "Remove Stock",
    "Damaged Items",
    "Inventory Correction",
    "Manual Count Adjustment",
)


def resolve_product_thumb_url(product):
    """Resolve thumbnail URL for a product with primary gallery image and legacy fallback."""
    try:
        primary = product.primary_image
    except Exception:
        primary = None

    if primary is not None and not str(getattr(primary, "file_path", "")).startswith("legacy:"):
        return url_for(
            "static",
            filename=f"uploads/products/{primary.product_id}/thumbs/{primary.file_name}",
        )
    if primary is not None:
        return url_for("static", filename="uploads/" + primary.file_name)
    if getattr(product, "image", None):
        return url_for("static", filename="uploads/" + product.image)
    return ""


def apply_inventory_adjustment(form, user):
    """Execute a stock adjustment with underflow protection and administrative override.

    Returns:
        (product, details, is_clamped)

    Raises:
        ValueError on invalid product, inactive state, zero quantity, or illegal underflow.
    """
    pid = integer(form.get("product_id"), 1)
    p = db.get_or_404(Product, pid)
    if not p.active:
        raise ValueError("This product is inactive.")

    reason = required(form.get("reason"), "Reason", 100)
    reference = (form.get("reference") or "").strip()[:40]
    notes = (form.get("notes") or "").strip()[:500]
    qty_val = form.get("quantity") or form.get("qty")
    base = integer(qty_val, -1000000)
    if not base:
        raise ValueError("Quantity must be nonzero.")

    raw_type = form.get("adjustment_type")
    if raw_type in (None, ""):
        atype = "Add Stock" if base > 0 else "Remove Stock"
        delta = base
    else:
        atype = raw_type.strip()
        if atype not in ADJUST_TYPES:
            raise ValueError("Choose a valid adjustment type.")
        if atype == "Add Stock":
            delta = abs(base)
        elif atype in ("Remove Stock", "Damaged Items"):
            delta = -abs(base)
        else:
            delta = base

    new_stock = p.stock + delta
    clamped = False
    if new_stock < 0:
        is_admin = getattr(getattr(user, "role", None), "name", "") == "Admin"
        if form.get("allow_override") == "1" and is_admin:
            applied = -p.stock
            if not applied:
                return p, "Stock is already zero; no change recorded.", True
            delta = applied
            clamped = True
        else:
            raise ValueError(
                "This adjustment would take stock below zero. "
                "Only an administrator override can clamp it at zero."
            )

    move(p, delta, atype, reason)
    details = f"{p.sku}: {delta:+d}; {reason}"
    if reference:
        details += f" [ref {reference}]"
    if notes:
        details += f" ({notes})"
    if clamped:
        details += f" (requested {base:+d}; clamped at zero by admin override)"

    audit("Adjust stock", details)
    db.session.commit()
    return p, details, clamped


def get_adjustment_page_data(selected_id, user, currency):
    """Compile dataset, recent adjustment movements, and JSON serialized products for the adjust UI."""
    products = Product.query.filter_by(active=True).all()
    selected = (
        db.session.get(Product, selected_id)
        if selected_id
        else (products[0] if products else None)
    )
    if selected is not None and not selected.active:
        selected = products[0] if products else None

    stock = stock_stats()
    day_start, _ = bounds(local_today(), local_today())
    adjust_kinds = ("Adjustment",) + ADJUST_TYPES
    today_count = (
        db.session.query(db.func.count(InventoryMovement.id))
        .filter(
            InventoryMovement.created_at >= day_start,
            InventoryMovement.kind.in_(adjust_kinds),
        )
        .scalar()
        or 0
    )
    recent = (
        InventoryMovement.query.filter(InventoryMovement.kind.in_(adjust_kinds))
        .order_by(InventoryMovement.id.desc())
        .limit(15)
        .all()
    )
    usernames = {u.id: u.name for u in User.query.all()}
    products_json = [
        {
            "id": p.id,
            "name": p.name,
            "sku": p.sku,
            "stock": p.stock,
            "minimum": p.minimum,
            "category": p.category.name if p.category else "",
            "supplier": p.supplier.name if p.supplier else "",
            "cost": f"{currency} {p.cost / 100:,.2f}",
            "price": f"{currency} {p.price / 100:,.2f}",
            "status": p.status,
            "image": resolve_product_thumb_url(p),
        }
        for p in products
    ]

    return {
        "products": products,
        "selected": selected.id if selected else None,
        "sel": selected,
        "stock": stock,
        "today_count": today_count,
        "recent": recent,
        "usernames": usernames,
        "products_json": products_json,
        "adjust_types": ADJUST_TYPES,
        "is_admin": getattr(getattr(user, "role", None), "name", "") == "Admin",
    }
