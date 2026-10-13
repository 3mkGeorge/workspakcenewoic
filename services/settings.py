"""Settings and administration domain service for StorePro.

Encapsulates store configuration validation, user administration,
profile security updates, and expense tracking.
"""

import re
from werkzeug.security import check_password_hash

from models import (
    Expense,
    Product,
    Purchase,
    Role,
    Sale,
    User,
    db,
)
from services.core import (
    DEFAULTS,
    audit,
    cents,
    integer,
    required,
    save_setting,
)
from services.dual_backup import validate_config
from services.uploads import save_image


def update_store_settings(form, files, root_dir, current_settings):
    """Validate and persist store settings, updating logo and logging backup audits."""
    values = form
    currency = values.get("currency")
    if currency not in ("EGP", "USD", "EUR", "SAR", "AED"):
        raise ValueError("Unsupported currency.")
    if currency != current_settings["currency"] and (
        Sale.query.first()
        or Purchase.query.first()
        or Expense.query.first()
        or Product.query.first()
    ):
        raise ValueError(
            "Currency is locked once prices or transactions exist, to prevent relabeling monetary values. Choose currency before entering products."
        )
    if values.get("language") not in ("en", "ar"):
        raise ValueError("Unsupported language.")
    if values.get("theme") not in ("light", "dark"):
        raise ValueError("Choose light or dark appearance.")
    if values.get("date_format") not in ("DD/MM/YYYY", "YYYY-MM-DD"):
        raise ValueError("Invalid date format.")
    from services.permissions import require

    backup_keys = [
        k for k in DEFAULTS if k.startswith("backup_") or k == "auto_backup"
    ]
    backup_toggles = {
        "auto_backup",
        "backup_live",
        "backup_compression",
        "backup_verification",
    }
    if any(
        ("1" if values.get(k) == "1" else "0") != current_settings[k]
        if k in backup_toggles
        else k in values and values[k] != current_settings[k]
        for k in backup_keys
    ):
        require("backups.edit")
    validate_config(root_dir, current_settings | values.to_dict())
    rate = cents(values.get("tax_rate"))
    if rate > 10000:
        raise ValueError("Tax must be between 0 and 100 percent.")
    for key in ("invoice_prefix", "purchase_prefix"):
        if not re.fullmatch(r"[A-Za-z0-9-]{1,12}", values.get(key, "")):
            raise ValueError(
                "Invoice prefixes must contain 1–12 letters, digits, or hyphens."
            )
    required(values.get("store_name"), "Store name", 100)
    integer(values.get("session_minutes"), 5, 480)
    integer(values.get("items_per_page"), 5, 100)
    integer(values.get("low_stock_default"), 0, 1000000)
    for key in DEFAULTS:
        if key == "logo":
            continue
        if key in (
            "tax_enabled",
            "auto_backup",
            "backup_live",
            "backup_compression",
            "backup_verification",
            "show_tax",
            "show_cashier",
            "show_barcode",
            "show_logo",
        ):
            save_setting(key, "1" if values.get(key) == "1" else "0")
        elif key in values:
            save_setting(key, values[key][:500])
    logo = save_image(files.get("logo"))
    if logo:
        save_setting("logo", logo)
    for key, label in (
        ("backup_primary", "Primary"),
        ("backup_secondary", "Secondary"),
    ):
        if key in values and values[key][:500] != current_settings.get(key, ""):
            audit(
                "Backup paths changed",
                f"{label}: {current_settings.get(key) or '(installation default)'} → {values[key][:500] or '(installation default)'} (via Settings)",
            )
    audit("Settings updated", "Store configuration saved")
    db.session.commit()


def save_managed_user(form):
    """Create or update an administrative user account with role enforcement."""
    from routes.auth import password
    from services.permissions import ensure_recovery_operator, guard_user_management

    user = (
        db.get_or_404(User, integer(form["id"], 1))
        if form.get("id")
        else User()
    )
    role = db.get_or_404(Role, integer(form.get("role_id"), 1))
    active = form.get("active") == "1"

    guard_user_management(user if user.id else None, role)
    user.name = required(form.get("name"), "Name", 100)
    user.username = required(form.get("username"), "Username", 80).lower()
    user.role_id = role.id
    user.active = active
    if form.get("password"):
        user.password_hash = password(form["password"])
    elif not user.id:
        raise ValueError("A password is required for a new account.")
    user.version = (user.version or 0) + 1
    db.session.add(user)
    db.session.flush()
    ensure_recovery_operator()
    audit("Save user", user.username)
    db.session.commit()
    return user


def update_account_password(user, current_password, new_password):
    """Change the authenticated user's password, bumping token version to invalidate sessions."""
    from routes.auth import password

    if not check_password_hash(user.password_hash, current_password):
        raise ValueError("Current password is incorrect.")
    user.password_hash = password(new_password)
    user.version += 1
    audit("Change password", "Account password changed")
    db.session.commit()


def create_expense_record(form, currency):
    """Validate and record an operational expense."""
    amount = cents(form.get("amount"))
    if amount <= 0:
        raise ValueError("Expense must be greater than zero.")
    e = Expense(
        description=required(form.get("description"), "Description", 200),
        amount=amount,
        currency=currency,
    )
    db.session.add(e)
    audit("Add expense", e.description)
    db.session.commit()
    return e
