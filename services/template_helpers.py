"""Template filters and context processors for StorePro.

Provides formatting for currency, dates, backup timestamps, and injects
global configuration, navigation permissions, and real-time alert counters.
"""

from datetime import timezone, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import request, g
from models import now, Product, ShippingOrder
from services.i18n import translate
from services.permissions import can
from services.startup import get_asset_version, get_app_version


def register_template_helpers(app):
    """Register custom Jinja2 template filters and context processors."""

    @app.url_defaults
    def add_static_version(endpoint, values):
        """Append deterministic cache-busting version query string to all static asset URLs."""
        if endpoint == "static" or endpoint.endswith(".static"):
            if "v" not in values:
                values["v"] = get_asset_version(values.get("filename"))

    @app.template_filter("money")
    def money(value, currency=None):
        return f"{currency or g.settings['currency']} {int(value or 0) / 100:,.2f}"

    @app.template_filter("backup_date")
    def backup_date(value):
        return (
            value.replace(tzinfo=timezone.utc)
            .astimezone(ZoneInfo("Africa/Cairo"))
            .strftime("%d/%m/%Y %H:%M")
        )

    @app.template_filter("date")
    def date(value, time=False):
        if not value:
            return "—"
        try:
            value = value.replace(tzinfo=timezone.utc).astimezone(
                ZoneInfo("Africa/Cairo")
            )
        except ZoneInfoNotFoundError:
            value = value + timedelta(hours=3)
        fmt = "%d/%m/%Y" if g.settings["date_format"] == "DD/MM/YYYY" else "%Y-%m-%d"
        return value.strftime(fmt + (" %I:%M %p" if time else ""))

    @app.template_filter("weekday")
    def weekday(value):
        try:
            value = value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Africa/Cairo"))
        except ZoneInfoNotFoundError:
            value = value + timedelta(hours=3)
        return value.strftime("%A")

    @app.context_processor
    def context():
        count = (
            Product.query.filter(
                Product.active == True, Product.stock <= Product.minimum
            ).count()
            if can("inventory.view")
            else 0
        )
        if can("sales.view"):
            try:
                cutoff = now() - timedelta(hours=24)
                count += (
                    ShippingOrder.query.filter(
                        ShippingOrder.status == "Pending",
                        ShippingOrder.created_at < cutoff,
                    ).count()
                    + ShippingOrder.query.filter_by(status="Returned").count()
                )
            except Exception:
                app.logger.exception("Shipping alert count failed")

        def altered_url(**changes):
            args = request.args.to_dict()
            args.update(changes)
            return request.path + "?" + urlencode(args)

        backup_service = app.extensions.get("backups")
        backup_warnings = (
            backup_service.snapshot()["warnings"]
            if backup_service and can("backups.view")
            else []
        )

        return dict(
            can=can,
            backup_warnings=backup_warnings,
            config=g.settings,
            current_user=g.user,
            now=now(),
            t=translate,
            alert_count=count,
            page_url=lambda p: altered_url(page=p),
            select_url=lambda p: altered_url(selected=p),
            app_version=get_app_version(),
            asset_version=get_asset_version(),
        )
