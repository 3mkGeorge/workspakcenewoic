"""Dashboard aggregation and telemetry metrics service for StorePro.

Extracts business logic, inventory KPIs, comparative baselines,
storage analytics, and system health status from routes into a dedicated service.
"""

import shutil
from pathlib import Path
from datetime import datetime, timedelta
from flask import current_app
from models import db, Sale, SaleItem, Product, Expense, Purchase, AuditLog, BackupLog, now
from services.analytics import stock_stats, sale_stats, bounds, local_today, trend
from services.shipping import stats as shipping_stats


def _delta(cur, prev):
    if not prev:
        return ("New", "up") if cur else ("—", "flat")
    pct = round((cur - prev) * 100 / prev, 1)
    arrow = "▲" if pct > 0 else "▼" if pct < 0 else "■"
    cls = "up" if pct > 0 else "down" if pct < 0 else "flat"
    return (f"{arrow} {abs(pct)}%", cls)


def _fmt_size(b):
    if b >= 1024 * 1024 * 1024:
        return f"{b / (1024**3):.2f} GB"
    if b >= 1024 * 1024:
        return f"{b / (1024**2):.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.0f} KB"
    return f"{b} B"


def get_system_health_metrics():
    """Compute database, storage, and backup health indicators."""
    try:
        db_path = (
            Path(db.engine.url.database)
            if hasattr(db.engine.url, "database") and db.engine.url.database
            else None
        )
        db_size_bytes = db_path.stat().st_size if db_path and db_path.is_file() else 0

        # Uploads directory size
        root = current_app.config.get("ROOT", Path("."))
        uploads_dir = root / "static" / "uploads"
        uploads_size = 0
        if uploads_dir.is_dir():
            for f in uploads_dir.rglob("*"):
                if f.is_file():
                    uploads_size += f.stat().st_size

        # Host volume disk usage
        try:
            disk_total, disk_used, disk_free = shutil.disk_usage(root)
            disk_pct = round((disk_used / disk_total) * 100, 1) if disk_total else 0
            disk_usage_str = f"{_fmt_size(disk_free)} free ({disk_pct}% used)"
        except Exception:
            disk_usage_str = "Available"

        # SQLite engine status & pages
        try:
            journal_mode = db.session.execute(db.text("PRAGMA journal_mode")).scalar()
            page_count = db.session.execute(db.text("PRAGMA page_count")).scalar() or 0
            db_status = f"Online ({journal_mode.upper() if journal_mode else 'WAL'})"
        except Exception:
            db_status = "Online"
            page_count = 0

        db_size_str = _fmt_size(db_size_bytes)
        db_size_sub = f"{page_count:,} pages" if page_count else "SQLite WAL Engine"

        backup_service = current_app.extensions.get("backups")
        backup_snap = backup_service.snapshot() if backup_service else {}

        failed_backups_count = BackupLog.query.filter_by(status="Failed").count()

        last_backup_val = backup_snap.get("last_backup")
        last_backup_dt = None
        if isinstance(last_backup_val, str):
            clean_str = last_backup_val.replace(" UTC", "").strip()
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    last_backup_dt = datetime.strptime(clean_str, fmt)
                    break
                except ValueError:
                    pass
        elif isinstance(last_backup_val, datetime):
            last_backup_dt = last_backup_val

        if not last_backup_dt:
            last_log = (
                BackupLog.query.filter_by(status="Success")
                .order_by(BackupLog.created_at.desc())
                .first()
            )
            if last_log:
                last_backup_dt = last_log.created_at

        if last_backup_dt:
            if getattr(last_backup_dt, "tzinfo", None):
                last_backup_dt = last_backup_dt.replace(tzinfo=None)
            diff = now() - last_backup_dt
            secs = max(0, int(diff.total_seconds()))
            if secs < 60:
                backup_age = "Just now"
            elif secs < 3600:
                backup_age = f"{secs // 60}m ago"
            elif secs < 86400:
                backup_age = f"{secs // 3600}h ago"
            else:
                backup_age = f"{secs // 86400}d ago"
            last_backup_str = last_backup_dt.strftime("%b %d, %H:%M")
        else:
            backup_age = "Never"
            last_backup_str = "None"

        warnings = backup_snap.get("warnings", [])
        backup_copies = backup_snap.get("count", 0)

        if failed_backups_count > 0:
            backup_status = f"{failed_backups_count} Failed"
            backup_status_cls = "red"
        elif warnings:
            backup_status = "Attention Needed"
            backup_status_cls = "orange"
        else:
            backup_status = "Healthy"
            backup_status_cls = "green"

        return {
            "db_status": db_status,
            "db_size": db_size_str,
            "db_size_sub": db_size_sub,
            "uploads_size": _fmt_size(uploads_size),
            "disk_usage": disk_usage_str,
            "backup_status": backup_status,
            "backup_status_cls": backup_status_cls,
            "backup_copies": backup_copies,
            "backup_age": backup_age,
            "last_backup": last_backup_str,
            "failed_backups": failed_backups_count,
            "warnings": warnings,
        }
    except Exception:
        current_app.logger.exception("Failed to collect system health")
        return {}


def get_dashboard_data(days=7, perm_can_settings=False, perm_can_sales=False):
    """Aggregate all statistics, top products, baselines, and health cards for the dashboard."""
    stock = stock_stats()
    a, b = bounds(local_today(), local_today())
    today = Sale.query.filter(Sale.created_at >= a, Sale.created_at < b).all()
    stats = sale_stats(today)
    stats["expenses"] = db.session.scalar(
        db.select(db.func.coalesce(db.func.sum(Expense.amount), 0)).where(
            Expense.created_at >= a, Expense.created_at < b
        )
    )
    stats["purchases"] = db.session.scalar(
        db.select(db.func.coalesce(db.func.sum(Purchase.total), 0)).where(
            Purchase.created_at >= a,
            Purchase.created_at < b,
            Purchase.status != "Cancelled",
        )
    )
    stats["customers"] = len(
        {s.customer_id for s in today if s.customer_id and s.status == "Completed"}
    )

    top = db.session.execute(
        db.select(
            SaleItem.name,
            Product.image,
            db.func.sum(SaleItem.quantity).label("units"),
            db.func.sum(SaleItem.quantity * SaleItem.price).label("revenue"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .join(Product, SaleItem.product_id == Product.id)
        .where(Sale.status == "Completed")
        .group_by(SaleItem.product_id, SaleItem.name, Product.image)
        .order_by(db.desc("units"))
        .limit(5)
    ).all()

    ship = shipping_stats() if perm_can_sales else None

    # Yesterday comparison
    yd = local_today() - timedelta(days=1)
    ya, yb = bounds(yd, yd)
    y_sales = Sale.query.filter(Sale.created_at >= ya, Sale.created_at < yb).all()
    y_stats = sale_stats(y_sales)
    y_stats["expenses"] = db.session.scalar(
        db.select(db.func.coalesce(db.func.sum(Expense.amount), 0)).where(
            Expense.created_at >= ya, Expense.created_at < yb
        )
    )
    y_stats["purchases"] = db.session.scalar(
        db.select(db.func.coalesce(db.func.sum(Purchase.total), 0)).where(
            Purchase.created_at >= ya,
            Purchase.created_at < yb,
            Purchase.status != "Cancelled",
        )
    )

    prev = {
        "sales": _delta(stats["total"], y_stats["total"]),
        "profit": _delta(stats["profit"], y_stats["profit"]),
        "expenses": _delta(stats["expenses"], y_stats["expenses"]),
        "purchases": _delta(stats["purchases"], y_stats["purchases"]),
    }

    activity = (
        AuditLog.query.order_by(AuditLog.id.desc()).limit(20).all()
        if perm_can_settings
        else []
    )

    system_health = get_system_health_metrics() if perm_can_settings else {}

    return {
        "stock": stock,
        "stats": stats,
        "chart": trend(days),
        "recent": Sale.query.order_by(Sale.created_at.desc()).limit(5).all(),
        "top": top,
        "pending": Purchase.query.filter(
            Purchase.status.in_(["Pending", "Processing"])
        ).count(),
        "ship": ship,
        "prev": prev,
        "activity": activity,
        "system_health": system_health,
    }
