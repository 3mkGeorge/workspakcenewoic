"""Delivery/shipping orders: list, details, tracking, status flow."""

from flask import Blueprint, current_app, g, jsonify, render_template, request
from models import COURIER_PROVIDERS, SHIPPING_TRANSITIONS, ShippingOrder, db
from services.core import audit
from services.shipping import (
    ADDRESS_FIELDS,
    address_lines,
    execute_order_transition,
    serialize_order as serialize,
    update_shipping_order_details,
)

shipping = Blueprint("shipping", __name__)

STATUS_BADGES = {
    "Pending": "secondary",
    "Preparing": "info",
    "Ready For Shipment": "purple",
    "Shipped": "orange",
    "Out For Delivery": "cyan",
    "Delivered": "success",
    "Failed Delivery": "danger",
    "Returned": "warning",
    "Cancelled": "darkred",
}


@shipping.get("/shipping")
def orders():
    page, cities, couriers = shipping_listing()
    return render_template(
        "shipping/index.html",
        title="Shipping Orders",
        page=page,
        statuses=list(SHIPPING_TRANSITIONS),
        badges=STATUS_BADGES,
        transitions=SHIPPING_TRANSITIONS,
        cities=cities,
        couriers=couriers,
        shipping_couriers=list(COURIER_PROVIDERS),
    )


def shipping_listing(base_query=None):
    """Shared shipping-order listing (filters + pagination + facets).

    Reused by the Orders hub shipping tab so both surfaces stay identical.
    """
    query = base_query if base_query is not None else ShippingOrder.query
    status_arg = request.args.get("status")
    if status_arg:
        matched = next(
            (s for s in SHIPPING_TRANSITIONS if s.lower() == status_arg.lower()),
            None,
        )
        if not matched:
            raise ValueError("Unknown shipping status.")
        query = query.filter_by(status=matched)
    if request.args.get("city"):
        query = query.filter(ShippingOrder.city == request.args["city"][:80])
    if request.args.get("courier"):
        query = query.filter(ShippingOrder.courier == request.args["courier"][:80])
    if request.args.get("from"):
        query = query.filter(
            ShippingOrder.created_at >= f"{request.args['from'][:10]} 00:00:00"
        )
    if request.args.get("to"):
        query = query.filter(
            ShippingOrder.created_at < f"{request.args['to'][:10]} 00:00:00"
        )
    q = request.args.get("q", "").strip()[:100]
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                ShippingOrder.order_number.ilike(like),
                ShippingOrder.tracking_code.ilike(like),
                ShippingOrder.customer_name.ilike(like),
                ShippingOrder.phone.ilike(like),
            )
        )
    page = query.order_by(ShippingOrder.id.desc()).paginate(
        page=max(1, request.args.get("page", 1, type=int)),
        per_page=int(g.settings["items_per_page"]),
        error_out=False,
    )
    cities = [
        r[0]
        for r in db.session.query(ShippingOrder.city)
        .filter(ShippingOrder.city != "")
        .distinct()
        .order_by(ShippingOrder.city)
        .all()
    ]
    couriers = [
        r[0]
        for r in db.session.query(ShippingOrder.courier)
        .filter(ShippingOrder.courier != "")
        .distinct()
        .order_by(ShippingOrder.courier)
        .all()
    ]
    return page, cities, couriers


@shipping.get("/shipping/<int:oid>")
def details(oid):
    from models import SHIPPING_STAGE_LABELS, SHIPPING_WORKFLOW

    order = db.get_or_404(ShippingOrder, oid)
    sale = order.sale
    # Invoice record is authoritative for customer identity, products and
    # totals; the shipping snapshot is only a fallback when unlinked.
    customer_name = sale.customer_name if sale else (order.customer_name or "—")
    customer_phone = (
        sale.customer.phone
        if sale and sale.customer and sale.customer.phone
        else (order.phone or "—")
    )
    stages = [
        {"key": key, "label": SHIPPING_STAGE_LABELS[key]} for key in SHIPPING_WORKFLOW
    ]
    try:
        stage_index = SHIPPING_WORKFLOW.index(order.status)
    except ValueError:
        # Legacy bridges sit on their nearest canonical stage.
        stage_index = {"Preparing": 1, "Failed Delivery": 4}.get(order.status, -1)
    action_labels = {
        target: (
            "Mark Packed"
            if target == "Packed"
            else "Mark Ready For Shipment"
            if target == "Ready For Shipment"
            else "Mark as Shipped"
            if target == "Shipped"
            else "Mark Out For Delivery"
            if target == "Out For Delivery"
            else "Mark as Delivered"
            if target == "Delivered"
            else "Mark Returned"
            if target == "Returned"
            else "Cancel Shipment"
            if target == "Cancelled"
            else f"Mark {target}"
        )
        for target in SHIPPING_TRANSITIONS.get(order.status, ())
    }
    return render_template(
        "shipping/details.html",
        title=order.order_number,
        order=order,
        sale=sale,
        customer_name=customer_name,
        customer_phone=customer_phone,
        address_lines=address_lines(order),
        address_incomplete=not (order.street and order.city),
        transitions=SHIPPING_TRANSITIONS.get(order.status, ()),
        action_labels=action_labels,
        stages=stages,
        stage_index=stage_index,
        badges=STATUS_BADGES,
        providers=COURIER_PROVIDERS,
    )


@shipping.get("/api/shipping/last-address")
def last_address():
    """Most recent delivery address for a customer (POS auto-fill)."""

    cid = request.args.get("customer_id", type=int)
    if not cid:
        return jsonify(address=None)
    order = (
        ShippingOrder.query.filter_by(customer_id=cid)
        .order_by(ShippingOrder.id.desc())
        .first()
    )
    if not order:
        return jsonify(address=None)
    return jsonify(
        address={field: getattr(order, field) or "" for field in ADDRESS_FIELDS}
    )


@shipping.get("/api/shipping/<int:oid>")
def order_detail(oid):
    """Full payload for the Shipment Details modal (read-only)."""

    order = db.get_or_404(ShippingOrder, oid)
    sale = order.sale
    events = []
    for event in order.events:
        try:
            at = current_app.jinja_env.filters["date"](event.created_at, True)
        except Exception:
            at = (
                event.created_at.isoformat(sep=" ", timespec="minutes")
                if event.created_at
                else ""
            )
        events.append({"action": event.action, "actor": event.actor, "at": at})
    items = []
    if sale:
        for item in sale.items:
            try:
                from services.product_media import primary_urls

                _full, thumb = (
                    primary_urls(item.product) if item.product else ("", "")
                )
            except Exception:
                thumb = ""
            items.append(
                {
                    "name": item.name,
                    "sku": item.product.sku if item.product else "",
                    "quantity": item.quantity,
                    "price": item.price,
                    "discount": item.discount,
                    "total": item.quantity * item.price - item.discount,
                    "image": thumb or "",
                }
            )
    try:
        created_display = current_app.jinja_env.filters["date"](
            order.created_at, True
        )
    except Exception:
        created_display = (
            order.created_at.isoformat(sep=" ", timespec="minutes")
            if order.created_at
            else ""
        )
    return jsonify(
        order=serialize(order),
        address={field: getattr(order, field) or "" for field in ADDRESS_FIELDS},
        address_lines=address_lines(order),
        address_incomplete=not (order.street and order.city),
        created_display=created_display,
        items=items,
        sale_totals=(
            {
                "subtotal": sale.subtotal,
                "discount": sale.discount,
                "tax": sale.tax,
                "tax_rate": sale.tax_rate,
                "total": sale.total,
                "currency": sale.currency,
            }
            if sale
            else None
        ),
        events=events,
        transitions=list(SHIPPING_TRANSITIONS.get(order.status, ())),
    )


@shipping.get("/api/shipping/<int:oid>/customer")
def order_customer(oid):
    """Customer profile payload for the Customer modal (read-only)."""
    from models import Customer

    order = db.get_or_404(ShippingOrder, oid)
    customer = (
        db.session.get(Customer, order.customer_id) if order.customer_id else None
    )
    if customer:
        profile = {
            "name": customer.name,
            "phone": customer.phone or "",
            "email": customer.email or "",
            "address": customer.address or "",
            "active": bool(customer.active),
        }
        peer_orders = ShippingOrder.query.filter_by(customer_id=customer.id).all()
    else:
        profile = {
            "name": order.customer_name or "",
            "phone": order.phone or "",
            "email": "",
            "address": ", ".join(
                p for p in [address_lines(order), order.city] if p
            ),
            "active": True,
        }
        peer_orders = (
            ShippingOrder.query.filter(
                ShippingOrder.customer_name == order.customer_name,
                ShippingOrder.customer_id.is_(None),
            ).all()
            if order.customer_name
            else []
        )
    delivered = sum(1 for o in peer_orders if o.status == "Delivered")
    return jsonify(
        profile=profile,
        stats={
            "shipments": len(peer_orders),
            "delivered": delivered,
            "open": sum(
                1
                for o in peer_orders
                if o.status not in ("Delivered", "Returned", "Cancelled")
            ),
        },
    )


@shipping.delete("/api/shipping/<int:oid>")
def delete_order(oid):
    """Delete a shipment only before any work happens on it.

    Guardrails (ledger stays append-only): the order must still be Pending
    and its timeline must hold nothing but the creation event. Anything
    else is refused with the exact reason.
    """
    order = db.get_or_404(ShippingOrder, oid)
    if order.status != "Pending":
        raise ValueError(
            f"Only Pending shipments can be deleted (current status: {order.status})."
        )
    extra = [e.action for e in order.events if e.action != "Order Created"]
    if extra:
        raise ValueError(
            f"Shipment already has activity ({', '.join(extra)}). "
            "Cancel it instead of deleting."
        )
    audit("Delete shipping order", f"{order.order_number} (no activity)")
    for event in list(order.events):
        db.session.delete(event)
    db.session.delete(order)
    db.session.commit()
    current_app.logger.info("shipping-delete order_id=%s", oid)
    return jsonify(deleted=True)


@shipping.get("/shipping/<int:oid>/label")
def label(oid):
    """Print-friendly shipping label (auto-print view)."""
    order = db.get_or_404(ShippingOrder, oid)
    return render_template(
        "shipping/label.html",
        title=f"Label {order.order_number}",
        order=order,
        address_lines=address_lines(order),
    )


@shipping.post("/api/shipping/<int:oid>")
def update_order(oid):
    """Assign courier / tracking / cost / shipment date. All changes logged."""
    order = db.get_or_404(ShippingOrder, oid)
    data = request.get_json(silent=True) or {}
    changed = update_shipping_order_details(order, data, g.user.name)
    return jsonify(
        order=serialize(order),
        changed=changed,
        transitions=list(SHIPPING_TRANSITIONS.get(order.status, ())),
    )


@shipping.post("/api/shipping/<int:oid>/status")
def transition(oid):
    order = db.get_or_404(ShippingOrder, oid)
    data = request.get_json(silent=True) or {}
    target = data.get("status", "")
    execute_order_transition(order, target, data, g.user.name)
    event = order.events[-1] if order.events else None
    at = None
    if event is not None:
        try:
            at = current_app.jinja_env.filters["date"](event.created_at, True)
        except Exception:
            at = event.created_at.isoformat(sep=" ", timespec="minutes")
    return jsonify(
        order=serialize(order),
        transitions=list(SHIPPING_TRANSITIONS.get(order.status, ())),
        event={"action": target, "actor": g.user.name, "at": at} if event else None,
    )
