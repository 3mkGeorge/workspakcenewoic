"""Category management domain service for StorePro.

Encapsulates category queries, statistics calculations, input validation,
product usage diagnostics, merge logic, and safe deletion/purge operations.
"""

import logging
import re
from sqlalchemy import case, func

from models import (
    Category,
    InventoryMovement,
    PriceHistory,
    Product,
    PurchaseItem,
    SaleItem,
    db,
    now,
)
from services.core import audit

logger = logging.getLogger(__name__)

COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

HISTORY_MODELS = (
    ("sale_items", SaleItem),
    ("purchase_items", PurchaseItem),
    ("inventory_movements", InventoryMovement),
    ("price_history", PriceHistory),
)


def clean_name(value):
    name = (value or "").strip()
    if len(name) < 2:
        raise ValueError("Category name needs at least 2 characters.")
    if len(name) > 100:
        raise ValueError("Category name must be 100 characters or fewer.")
    return name


def clean_color(value):
    color = (value or "").strip()
    if color and not COLOR_RE.fullmatch(color):
        raise ValueError("Color tag must be a hex value such as #3b82f6.")
    return color


def clean_icon(value):
    icon = (value or "").strip()[:40]
    if icon and not re.fullmatch(r"[a-z0-9-]+", icon):
        raise ValueError("Icon must use lowercase letters, digits or hyphens.")
    return icon


def check_duplicate(name, exclude_id=None):
    query = Category.query.filter(func.lower(Category.name) == name.lower())
    if exclude_id:
        query = query.filter(Category.id != exclude_id)
    if query.first():
        raise ValueError(f'A category named "{name}" already exists.')


def diagnose_category_usage(cid):
    """Single source of truth for which products block category deletion.

    Counts every product row referencing the category (both active and archived).
    Returns [(id, name, active)].
    """
    query = (
        db.session.query(Product.id, Product.name, Product.active)
        .filter(Product.category_id == cid)
        .order_by(Product.id)
    )
    rows = query.all()
    active_ids = [r[0] for r in rows if r[2]]
    archived_ids = [r[0] for r in rows if not r[2]]
    try:
        sql = str(query.statement.compile(compile_kwargs={"literal_binds": True}))
    except Exception:
        sql = f"products WHERE category_id = {cid!r}"
    logger.info(
        "category-usage-check category_id=%s products_found=%s active=%s archived=%s "
        "product_ids=%s active_ids=%s archived_ids=%s sql=%s",
        cid,
        len(rows),
        len(active_ids),
        len(archived_ids),
        [r[0] for r in rows],
        active_ids,
        archived_ids,
        sql,
    )
    return rows


def history_references(pid):
    """Count ledger rows pinning a product. Nonzero = hard delete would break FK."""
    return {
        label: model.query.filter_by(product_id=pid).count()
        for label, model in HISTORY_MODELS
    }


def stats_query():
    """SQLAlchemy query returning category rows with aggregated product counts, units, and inventory value."""
    return (
        db.session.query(
            Category,
            func.sum(case((Product.active == True, 1), else_=0)).label("products"),
            func.coalesce(
                func.sum(case((Product.active == True, Product.stock), else_=0)), 0
            ).label("units"),
            func.coalesce(
                func.sum(
                    case((Product.active == True, Product.stock * Product.cost), else_=0)
                ),
                0,
            ).label("value"),
            func.count(Product.id).label("total"),
        )
        .outerjoin(Product, Product.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.name)
    )


def serialize(row):
    """Serialize a Category entity or (Category, products, units, value, total) tuple to a dict."""
    category, products, units, value, total = row
    total = int(total or 0)
    active = int(products or 0)
    return {
        "id": category.id,
        "name": category.name,
        "description": category.description or "",
        "color": category.color or "",
        "icon": category.icon or "",
        "products": active,
        "units": int(units or 0),
        "value": int(value or 0),
        "total": total,
        "archived": total - active,
        "created": category.created_at.strftime("%d/%m/%Y")
        if category.created_at
        else "—",
    }


def create_category_record(data):
    """Create a new category from validated input data."""
    name = clean_name(data.get("name"))
    check_duplicate(name)
    category = Category(
        name=name,
        description=(data.get("description") or "").strip()[:500],
        color=clean_color(data.get("color")),
        icon=clean_icon(data.get("icon")),
        created_at=now(),
        updated_at=now(),
    )
    db.session.add(category)
    audit("Category Created", name)
    db.session.commit()
    return category


def update_category_record(category, data):
    """Update an existing category record with audit logging."""
    old_name = category.name
    if "name" in data:
        name = clean_name(data.get("name"))
        check_duplicate(name, exclude_id=category.id)
        category.name = name
    if "description" in data:
        category.description = (data.get("description") or "").strip()[:500]
    if "color" in data:
        category.color = clean_color(data.get("color"))
    if "icon" in data:
        category.icon = clean_icon(data.get("icon"))
    category.updated_at = now()
    audit("Category Edited", f"{old_name} → {category.name}")
    db.session.commit()
    return stats_query().filter(Category.id == category.id).one()


def merge_categories_records(source_id, target_id):
    """Merge source category into target category, reassigning products and deleting source."""
    if source_id == target_id:
        raise ValueError("Source and target categories must differ.")
    source = db.get_or_404(Category, source_id)
    target = db.get_or_404(Category, target_id)
    usage = diagnose_category_usage(source.id)
    moved = Product.query.filter_by(category_id=source.id).update(
        {"category_id": target.id}, synchronize_session=False
    )
    logger.info(
        "category-merge category_id=%s target_id=%s products_found=%s moved=%s",
        source.id,
        target.id,
        len(usage),
        moved,
    )
    audit("Category Merged", f"{source.name} ({moved} products) → {target.name}")
    db.session.delete(source)
    db.session.commit()
    return moved, target.id


def delete_category_record(category, data):
    """Delete a category, moving products to a target or new category if needed."""
    cid = category.id
    usage = diagnose_category_usage(cid)
    count = len(usage)
    if count:
        mode = data.get("mode")
        if mode == "move":
            try:
                target_id = int(data.get("target_id"))
            except (TypeError, ValueError):
                raise ValueError("Choose a category to move products into.")
            if target_id == cid:
                raise ValueError("Move products to a different category.")
            target = db.get_or_404(Category, target_id)
            Product.query.filter_by(category_id=cid).update(
                {"category_id": target.id}, synchronize_session=False
            )
            audit(
                "Category Deleted",
                f"{category.name} ({count} products moved to {target.name})",
            )
        elif mode == "new":
            name = clean_name(data.get("new_name"))
            check_duplicate(name)
            target = Category(name=name, created_at=now(), updated_at=now())
            db.session.add(target)
            db.session.flush()
            Product.query.filter_by(category_id=cid).update(
                {"category_id": target.id}, synchronize_session=False
            )
            audit(
                "Category Deleted",
                f"{category.name} ({count} products moved to new category {name})",
            )
        else:
            raise ValueError(
                "This category holds products. Move them first — orphan products are not allowed."
            )
    else:
        audit("Category Deleted", category.name)
    db.session.delete(category)
    db.session.commit()


def purge_category_record(category):
    """Permanently delete archived products (history-free only) and their category.

    Raises ValueError if active products remain, if category is empty, or if foreign keys block deletion.
    """
    cid = category.id
    usage = diagnose_category_usage(cid)
    actives = [r for r in usage if r[2]]
    if actives:
        raise ValueError(
            f"{len(actives)} active product(s) remain — move them first. "
            "Purge only removes archived products."
        )
    if not usage:
        raise ValueError("Nothing to purge: the category is already empty.")

    blockers = []
    for pid, pname, _active in usage:
        refs = history_references(pid)
        pinned = {k: v for k, v in refs.items() if v}
        if pinned:
            blockers.append(
                f"'{pname}' (referenced by "
                + ", ".join(f"{v} {k}" for k, v in sorted(pinned.items()))
                + ")"
            )
    if blockers:
        logger.info(
            "category-purge-blocked category_id=%s blockers=%s", cid, blockers
        )
        raise ValueError(
            "Cannot permanently delete: "
            + "; ".join(blockers)
            + ". Move these products instead."
        )

    from services.product_media import delete_product_files

    purged = []
    for pid, _pname, _active in usage:
        product = db.session.get(Product, pid)
        if product is None:
            continue
        delete_product_files(product)
        db.session.delete(product)
        purged.append(pid)

    logger.info(
        "category-purge category_id=%s purged_product_ids=%s", cid, purged
    )
    audit(
        "Category Deleted",
        f"{category.name} ({len(purged)} archived product(s) permanently removed)",
    )
    db.session.delete(category)
    db.session.commit()
    return purged
