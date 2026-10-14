import json
import secrets
from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from models import (
    Customer,
    Product,
    Purchase,
    PurchaseItem,
    Sale,
    SaleItem,
    SalePayment,
    Supplier,
    db,
)
from services.analytics import bounds, date_range, sale_stats, trend
from services.core import audit, integer
from services.sales import (
    advance_pickup_order,
    create_purchase_order,
    receive_purchase,
    reverse_sale,
    serialize_sale_detail,
    write_sale,
)

transactions = Blueprint("transactions", __name__)


@transactions.get("/sales")
def sales():
    start, end = date_range()
    a, b = bounds(start, end)
    query = Sale.query.filter(Sale.created_at >= a, Sale.created_at < b)
    q = request.args.get("q", "")[:100]
    if q:
        query = query.filter(
            db.or_(
                Sale.invoice.contains(q, autoescape=True),
                Sale.customer_name.contains(q, autoescape=True),
                Sale.items.any(SaleItem.name.contains(q, autoescape=True)),
            )
        )
    if request.args.get("payment"):
        method = request.args["payment"]
        methods = {
            "Card": ["Card", "Visa", "Mastercard"],
            "Mobile Wallet": ["Mobile Wallet", "Wallet"],
        }.get(method, [method])
        query = query.filter(
            db.or_(
                Sale.payment.in_(methods),
                Sale.payments.any(SalePayment.method.in_(methods)),
            )
        )
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    stats = sale_stats(query.all())
    page = query.order_by(Sale.id.desc()).paginate(
        page=max(1, request.args.get("page", 1, type=int)),
        per_page=int(g.settings["items_per_page"]),
        error_out=False,
    )
    requested = (
        db.session.get(Sale, request.args.get("selected", type=int))
        if request.args.get("selected", type=int)
        else None
    )
    selected = requested or (page.items[0] if page.items else None)
    return render_template(
        "sales/index.html",
        title="Sales",
        page=page,
        selected=selected,
        open_sale=requested.id if requested else None,
        stats=stats,
        start=start,
        end=end,
    )


@transactions.route("/sales/new", methods=["GET", "POST"])
@transactions.route("/sales/<int:sid>/edit", methods=["GET", "POST"])
def sale_form(sid=None):
    sale = db.get_or_404(Sale, sid) if sid else None
    if sale and sale.status != "Completed":
        raise ValueError("Only completed sales can be edited.")
    if request.method == "GET" and (not sale or sale.payments):
        from routes.pos import render_pos

        return render_pos(sale)
    if request.method == "POST":
        if sale and sale.payments:
            raise ValueError(
                "Open the POS editor to preserve item discounts and split payments."
            )
        duplicate = (
            Sale.query.filter_by(token=request.form.get("token")).first()
            if not sale
            else None
        )
        with current_app.config["DB_LOCK"]:
            saved = duplicate or write_sale(request.form, sale)
            db.session.commit()
        flash("Invoice saved and stock updated.", "success")
        return redirect(url_for("transactions.sales", selected=saved.id))
    return render_template(
        "sales/form.html",
        title="Edit Sale" if sale else "New Sale",
        sale=sale,
        products=Product.query.filter_by(active=True).all(),
        customers=Customer.query.filter_by(active=True).order_by(Customer.name).all(),
        token=secrets.token_hex(24),
    )


@transactions.get("/api/sales/<int:sid>")
def sale_detail(sid):
    """Invoice Details modal payload. Read-only; permission via STATIC map."""
    sale = db.get_or_404(Sale, sid)
    return jsonify(**serialize_sale_detail(sale))


@transactions.post("/api/sales/<int:sid>/pickup-status")
def pickup_status(sid):
    """Advance a pickup order: Pending Pickup → Ready For Pickup → Collected."""
    from models import PICKUP_TRANSITIONS

    sale = db.get_or_404(Sale, sid)
    data = request.get_json(silent=True) or {}
    status = advance_pickup_order(sale, data.get("status", ""))
    return jsonify(
        status=status,
        transitions=list(PICKUP_TRANSITIONS.get(status, ())),
    )


@transactions.post("/sales/<int:sid>/<action>")
def sale_action(sid, action):
    if action not in ("refund", "delete"):
        raise ValueError("Unknown sale action.")
    payload = request.get_json(silent=True) or {}
    reason = payload.get("cancel_reason", request.form.get("cancel_reason", ""))
    if action == "delete" and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError("A cancellation reason is required.")
    is_itemized_refund = False
    # Serialize refunds/voids: the invoice is loaded and its status checked only
    # once any concurrent request on it has committed, so a double submit (two
    # tabs, a retry) cannot restore the same stock twice.
    with current_app.config["DB_LOCK"]:
        db.session.expire_all()
        sale = db.get_or_404(Sale, sid)
        if action == "refund":
            items = payload.get("items")
            if items and isinstance(items, list):
                from services.sales import refund_sale_items

                refund_sale_items(sale, items)
                is_itemized_refund = True
            else:
                reverse_sale(sale, "Refunded")
        elif action == "delete":
            reverse_sale(sale, "Voided")
            from models import now as model_now

            sale.cancel_reason = reason.strip()[:200]
            sale.cancelled_at = model_now()
        db.session.commit()
    if request.is_json and is_itemized_refund:
        return jsonify(
            success=True,
            invoice=sale.invoice,
            status=sale.status,
            total=sale.total,
        )
    flash(
        "Invoice refunded."
        if action == "refund"
        else "Invoice voided. The original is retained for the audit trail.",
        "success",
    )
    return redirect(url_for("transactions.sales", selected=sid))


@transactions.get("/sales/<int:sid>/invoice")
def invoice(sid):
    sale = db.get_or_404(Sale, sid)
    return render_template(
        "sales/invoice.html",
        sale=sale,
        store=json.loads(sale.store_snapshot),
        receipt=request.args.get("receipt") == "1",
        title=sale.invoice,
    )


@transactions.get("/purchases")
def purchases():
    start, end = date_range()
    a, b = bounds(start, end)
    status = request.args.get("status", "")
    query = Purchase.query
    # "open" (Pending + Processing) lists every open order, like the dashboard
    # count it comes from, unless a date range is chosen explicitly.
    if status != "open" or request.args.get("from") or request.args.get("to"):
        query = query.filter(Purchase.created_at >= a, Purchase.created_at < b)
    q = request.args.get("q", "")[:100]
    if q:
        query = query.filter(
            db.or_(
                Purchase.invoice.contains(q, autoescape=True),
                Purchase.supplier_name.contains(q, autoescape=True),
                Purchase.items.any(PurchaseItem.name.contains(q, autoescape=True)),
            )
        )
    if request.args.get("supplier_id"):
        query = query.filter_by(supplier_id=integer(request.args["supplier_id"], 1))
    if status == "open":
        query = query.filter(Purchase.status.in_(("Pending", "Processing")))
    elif status:
        query = query.filter_by(status=status)
    rows = query.all()
    page = query.order_by(Purchase.id.desc()).paginate(
        page=max(1, request.args.get("page", 1, type=int)),
        per_page=int(g.settings["items_per_page"]),
        error_out=False,
    )
    selected = (
        db.session.get(Purchase, request.args.get("selected", type=int))
        if request.args.get("selected", type=int)
        else None
    )
    stats = dict(
        total=sum(p.total for p in rows if p.status != "Cancelled"),
        count=len(rows),
        suppliers=Supplier.query.filter_by(active=True).count(),
        received=sum(
            i.quantity for p in rows if p.status == "Received" for i in p.items
        ),
        pending=sum(p.status in ("Pending", "Processing") for p in rows),
    )
    top = db.session.execute(
        db.select(
            Purchase.supplier_name,
            db.func.count(Purchase.id),
            db.func.sum(Purchase.total).label("amount"),
        )
        .where(
            Purchase.status != "Cancelled",
            Purchase.created_at >= a,
            Purchase.created_at < b,
        )
        .group_by(Purchase.supplier_name)
        .order_by(db.desc("amount"))
        .limit(5)
    ).all()
    return render_template(
        "purchases/index.html",
        title="Purchases",
        page=page,
        selected=selected,
        stats=stats,
        start=start,
        end=end,
        suppliers=Supplier.query.filter_by(active=True).all(),
        chart=trend((end - start).days + 1, end),  # follows the From/To filter
        top=top,
    )


@transactions.route("/purchases/new", methods=["GET", "POST"])
def purchase_form():
    if request.method == "POST":
        duplicate = Purchase.query.filter_by(token=request.form.get("token")).first()
        if duplicate:
            return redirect(url_for("transactions.purchases", selected=duplicate.id))
        order = create_purchase_order(request.form)
        flash("Purchase order saved.", "success")
        return redirect(url_for("transactions.purchases", selected=order.id))
    return render_template(
        "purchases/form.html",
        title="New Purchase Order",
        products=Product.query.filter_by(active=True).all(),
        suppliers=Supplier.query.filter_by(active=True).all(),
        token=secrets.token_hex(24),
    )


@transactions.post("/purchases/<int:pid>/<action>")
def purchase_action(pid, action):
    order = db.get_or_404(Purchase, pid)
    if action == "receive":
        receive_purchase(order)
    elif action in ("cancel", "process") and order.status in ("Pending", "Processing"):
        order.status = "Cancelled" if action == "cancel" else "Processing"
        audit("Update purchase", f"{order.invoice}: {order.status}")
    else:
        raise ValueError("This order cannot be changed.")
    db.session.commit()
    return redirect(url_for("transactions.purchases", selected=pid))
