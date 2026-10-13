from flask import Blueprint, jsonify, request, g, redirect, url_for, flash, send_file
from models import db, Product, PriceHistory
from services.core import integer, audit
from services.prices import price_summary, price_trend, serialize

price_history = Blueprint("price_history", __name__)


@price_history.get("/api/products/<int:pid>/price-history")
def history(pid):
    product = db.get_or_404(Product, pid)
    query = PriceHistory.query.filter_by(product_id=pid)
    if request.args.get("before"):
        query = query.filter(PriceHistory.id < integer(request.args["before"], 1))
    rows = query.order_by(PriceHistory.id.desc()).limit(11).all()
    summary = price_summary(product)
    # Range-aware trend for the analytics popup: 7 / 30 / 90 / all.
    # Default (no range) keeps the legacy last-30 behavior for backwards compat.
    wanted = (request.args.get("range") or "").strip().lower()
    if wanted in ("7", "7d", "7days"):
        summary["trend"] = price_trend(pid, days=7)
    elif wanted in ("30", "30d", "30days"):
        summary["trend"] = price_trend(pid, days=30)
    elif wanted in ("90", "90d", "90days"):
        summary["trend"] = price_trend(pid, days=90)
    elif wanted in ("all", "alltime", "all-time"):
        summary["trend"] = price_trend(pid, days=None)
    return jsonify(
        product_id=pid,
        items=[serialize(r) for r in rows[:10]],
        next_cursor=rows[9].id if len(rows) > 10 else None,
        summary=summary,
        currency=g.settings["currency"],
        alerts_enabled=product.price_alerts,
    )


@price_history.post("/products/<int:pid>/price-alerts")
def alerts(pid):
    product = db.get_or_404(Product, pid)
    enabled = request.form.get("enabled")
    if enabled not in ("0", "1"):
        raise ValueError("Choose an alert preference.")
    product.price_alerts = enabled == "1"
    audit(
        "Price alert preference",
        f"{product.sku}: {'enabled' if product.price_alerts else 'disabled'}",
    )
    db.session.commit()
    flash("Price alerts updated.", "success")
    return redirect(url_for("catalog.products", selected=pid))


@price_history.get("/products/<int:pid>/price-history/export/<fmt>")
def export(pid, fmt):
    product = db.get_or_404(Product, pid)
    if fmt not in ("xlsx", "pdf"):
        from flask import abort

        abort(404)
    rows = (
        PriceHistory.query.filter_by(product_id=pid)
        .order_by(PriceHistory.id.desc())
        .all()
    )
    from services.price_exports import export_history

    stream, mime = export_history(product, rows, fmt, g.settings["currency"])
    audit("Export price history", f"{product.sku}: {fmt}")
    db.session.commit()
    return send_file(
        stream,
        as_attachment=True,
        download_name=f"StorePro-price-history-{pid}.{fmt}",
        mimetype=mime,
    )
