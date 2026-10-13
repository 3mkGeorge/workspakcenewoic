"""Core foundational helpers, settings management, and inventory movement guards.

Re-exports validation and transaction utilities for backwards compatibility.
"""

from flask import g
from sqlalchemy import update
from models import AuditLog, InventoryMovement, Product, Setting, User, db, now
from services.sales import (
    lines_from_form,
    next_number,
    receive_purchase,
    reverse_sale,
    write_sale,
)
from services.validation import (
    cents,
    escape_formula,
    integer,
    required,
    sanitize_formula,
)

__all__ = [
    "DEFAULTS",
    "settings",
    "save_setting",
    "audit",
    "move",
    "cents",
    "integer",
    "required",
    "sanitize_formula",
    "escape_formula",
    "lines_from_form",
    "next_number",
    "write_sale",
    "reverse_sale",
    "receive_purchase",
]

DEFAULTS = {
    "store_name": "StorePro",
    "language": "en",
    "currency": "EGP",
    "tax_rate": "14",
    "tax_enabled": "1",
    "phone": "",
    "email": "",
    "address": "",
    "invoice_prefix": "INV-",
    "purchase_prefix": "PO-",
    "receipt_header": "Thank you for shopping with us!",
    "receipt_footer": "Please keep your receipt for returns.",
    "items_per_page": "10",
    "session_minutes": "30",
    "auto_backup": "1",
    "backup_frequency": "Daily",
    "backup_primary": "",
    "backup_secondary": "",
    "backup_retention": "50",
    "backup_live": "1",
    "backup_compression": "1",
    "backup_verification": "1",
    "theme": "light",
    "date_format": "DD/MM/YYYY",
    "show_tax": "1",
    "show_cashier": "1",
    "show_barcode": "1",
    "show_logo": "1",
    "logo": "",
    "low_stock_default": "5",
}


def settings():
    """Retrieve all configuration keys merged with store defaults."""
    return DEFAULTS | {s.key: s.value for s in db.session.scalars(db.select(Setting))}


def save_setting(key, value):
    """Persist a single configuration setting key/value pair."""
    row = db.session.get(Setting, key)
    if row:
        row.value = str(value)
    else:
        db.session.add(Setting(key=key, value=str(value)))


def audit(action, details):
    """Record an audit trail event for administrative compliance."""
    user = getattr(g, "user", None)
    db.session.add(
        AuditLog(
            user_id=user.id if user else None,
            actor=user.name if user else "System",
            action=action,
            details=str(details),
        )
    )


def move(product, delta, kind, reference, user_id=None):
    """Guarded atomic inventory mutation prevents overselling under concurrent requests."""
    result = db.session.execute(
        update(Product)
        .where(Product.id == product.id, Product.stock + delta >= 0)
        .values(stock=Product.stock + delta, updated_at=now())
    )
    if result.rowcount != 1:
        raise ValueError(f"Insufficient stock: {product.name}.")
    db.session.refresh(product)
    if not user_id:
        user = getattr(g, "user", None)
        user_id = user.id if user else (db.session.scalar(db.select(User.id).order_by(User.id.asc())) or 1)
    db.session.add(
        InventoryMovement(
            product_id=product.id,
            quantity=delta,
            balance=product.stock,
            cost=product.cost,
            kind=kind,
            reference=reference,
            user_id=user_id,
        )
    )
