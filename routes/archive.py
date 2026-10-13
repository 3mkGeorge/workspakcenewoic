"""Archived Products Center API. Restores are audited; permanent deletes are
refused while any sales, purchase, stock-movement or price history pins them."""

from flask import Blueprint, current_app, g, jsonify, request

from models import (
    AuditLog,
    InventoryMovement,
    PurchaseItem,
    SaleItem,
    Product,
    db,
)
from services.core import audit, integer
from services.product_media import delete_product_files, serialize_image

archive = Blueprint("archive", __name__)


def archived_by_map(skus):
    """Latest 'Archive product' actor per SKU. Products carry no archived_by
    column, so the audit trail is the source of truth (read-only reuse)."""
    if not skus:
        return {}
    rows = (
        AuditLog.query.filter(
            AuditLog.action == "Archive product",
            AuditLog.details.in_(list(skus)),
        )
        .order_by(AuditLog.id.desc())
        .all()
    )
    out = {}
    for row in rows:
        out.setdefault(row.details, row.actor)
    return out


def serialize_archived(product, archived_by=""):
    try:
        from services.product_media import primary_urls

        _full, thumb = primary_urls(product)
    except Exception:
        thumb = ""
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "barcode": product.barcode or "",
        "brand": product.brand or "",
        "category": product.category.name if product.category else "—",
        "category_id": product.category_id,
        "supplier": product.supplier.name if product.supplier else "—",
        "supplier_id": product.supplier_id,
        "cost": product.cost,
        "price": product.price,
        "stock": product.stock,
        "minimum": product.minimum,
        "location": product.location or "",
        "thumb": thumb or "",
        "status": "ARCHIVED",
        "archived_by": archived_by,
        "archived_at": product.updated_at.strftime("%d/%m/%Y %H:%M")
        if product.updated_at
        else "—",
        "created_at": product.created_at.strftime("%d/%m/%Y")
        if product.created_at
        else "—",
    }


def history_breakdown(pid):
    from services.categories import history_references

    return {k: v for k, v in history_references(pid).items() if v}


@archive.get("/api/archived")
@archive.get("/api/products/archived")
def list_archived():
    query = Product.query.filter_by(active=False)
    if request.args.get("q", "").strip():
        q = request.args["q"].strip()[:100]
        query = query.filter(
            db.or_(
                Product.name.contains(q, autoescape=True),
                Product.sku.contains(q, autoescape=True),
                Product.barcode.contains(q, autoescape=True),
            )
        )
    if request.args.get("category_id"):
        query = query.filter(
            Product.category_id == integer(request.args["category_id"], 1)
        )
    if request.args.get("supplier_id"):
        query = query.filter(
            Product.supplier_id == integer(request.args["supplier_id"], 1)
        )
    if request.args.get("from"):
        query = query.filter(Product.updated_at >= f"{request.args['from'][:10]} 00:00:00")
    if request.args.get("to"):
        query = query.filter(Product.updated_at < f"{request.args['to'][:10]} 00:00:00")
    sort = request.args.get("sort", "newest")
    if sort == "name":
        query = query.order_by(Product.name)
    elif sort == "oldest":
        query = query.order_by(Product.updated_at.asc())
    elif sort == "stock":
        query = query.order_by(Product.stock.desc())
    else:
        query = query.order_by(Product.updated_at.desc())
    items = query.all()
    by_map = archived_by_map({p.sku for p in items})
    return jsonify(
        total=len(items),
        currency=g.settings["currency"],
        products=[serialize_archived(p, by_map.get(p.sku, "")) for p in items],
    )


@archive.get("/api/archived/<int:pid>")
def archived_details(pid):
    product = db.get_or_404(Product, pid)
    if product.active:
        raise ValueError("This product is not archived.")
    data = serialize_archived(
        product, archived_by_map({product.sku}).get(product.sku, "")
    )
    data["status"] = "ARCHIVED"
    data["sales"] = SaleItem.query.filter_by(product_id=pid).count()
    data["purchases"] = PurchaseItem.query.filter_by(product_id=pid).count()
    data["movements"] = InventoryMovement.query.filter_by(product_id=pid).count()
    from services.product_media import ordered_records

    data["images"] = [serialize_image(r) for r in ordered_records(pid)]
    return jsonify(product=data)


@archive.post("/api/archived/<int:pid>/restore")
@archive.post("/api/products/<int:pid>/restore")
def restore_archived(pid):
    product = db.get_or_404(Product, pid)
    if product.active:
        raise ValueError("This product is already active.")
    product.active = True
    audit("Product Restored", f"{product.sku} ({product.name})")
    db.session.commit()
    current_app.logger.info(
        "archived-restore product_id=%s sku=%s", product.id, product.sku
    )
    return jsonify(product=serialize_archived(product))


@archive.delete("/api/archived/<int:pid>")
@archive.delete("/api/products/<int:pid>/permanent")
def delete_archived(pid):
    product = db.get_or_404(Product, pid)
    if product.active:
        raise ValueError("Only archived products can be permanently deleted.")
    refs = history_breakdown(pid)
    if refs:
        current_app.logger.info(
            "archived-delete-blocked product_id=%s refs=%s", pid, refs
        )
        parts = "; ".join(
            f"{v} {k.replace('_', ' ')}" for k, v in sorted(refs.items())
        )
        raise ValueError(
            f"Cannot permanently delete. Referenced by: {parts}."
        )
    delete_product_files(product)
    audit(
        "Product Permanently Deleted",
        f"{product.sku} ({product.name}) — no linked records remained",
    )
    db.session.delete(product)
    db.session.commit()
    current_app.logger.info("archived-delete product_id=%s sku=%s", pid, product.sku)
    return jsonify(deleted=True)
