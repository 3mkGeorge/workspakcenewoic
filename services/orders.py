"""Orders and fulfillment domain service for StorePro.

Provides cross-surface fulfillment aggregation: order hub counters,
pickup lifecycle queries, cancelled/voided listings, and returned/refunded ledgers.
"""

from models import (
    PICKUP_TRANSITIONS,
    SHIPPING_TRANSITIONS,
    Sale,
    ShippingOrder,
    db,
)
from services.analytics import bounds
from sqlalchemy.orm import joinedload

OPEN_SHIPPING = tuple(status for status, nxt in SHIPPING_TRANSITIONS.items() if nxt)
TERMINAL_SALES = ("Refunded", "Voided")


def get_orders_hub_counters():
    """Calculate open count badges across fulfillment tabs (shipping, pickup, cancelled, returns)."""
    shipping = (
        ShippingOrder.query.join(Sale, ShippingOrder.sale_id == Sale.id)
        .filter(
            ShippingOrder.status.in_(OPEN_SHIPPING),
            Sale.status.notin_(TERMINAL_SALES),
        )
        .count()
    )
    pickup = (
        Sale.query.filter(
            Sale.status == "Completed",
            Sale.pickup_status != "",
        ).count()
    )
    cancelled = ShippingOrder.query.filter_by(status="Cancelled").count() + (
        Sale.query.filter_by(status="Voided").count()
    )
    returns = ShippingOrder.query.filter_by(status="Returned").count() + (
        Sale.query.filter_by(status="Refunded").count()
    )
    pending = ShippingOrder.query.filter_by(status="Pending").count()
    packed = ShippingOrder.query.filter(
        ShippingOrder.status.in_(("Packed", "Preparing"))
    ).count()
    ready = ShippingOrder.query.filter_by(status="Ready For Shipment").count()
    shipped = ShippingOrder.query.filter_by(status="Shipped").count()
    out_for_delivery = ShippingOrder.query.filter_by(status="Out For Delivery").count()
    delivered = ShippingOrder.query.filter_by(status="Delivered").count()
    # The pipeline's "All" stage lists every shipment (pickups have their own tab).
    total_all = ShippingOrder.query.count()
    return {
        "shipping": shipping,
        "pickup": pickup,
        "cancelled": cancelled,
        "returns": returns,
        "all": total_all,
        "pending": pending,
        "packed": packed,
        "ready": ready,
        "shipped": shipped,
        "out_for_delivery": out_for_delivery,
        "delivered": delivered,
    }


def get_pickup_rows(pickup_status, start, end, search_text=""):
    """Fetch pickup order sales with available transitions and optional search filter."""
    a, b = bounds(start, end)
    query = Sale.query.filter(
        Sale.status == "Completed",
        Sale.pickup_status != "",
        Sale.created_at >= a,
        Sale.created_at < b,
    )
    q = (search_text or "").strip()[:100]
    if q:
        query = query.filter(
            db.or_(
                Sale.invoice.contains(q, autoescape=True),
                Sale.customer_name.contains(q, autoescape=True),
            )
        )
    rows = query.order_by(Sale.id.desc()).all()
    out = [
        {
            "sale": s,
            "transitions": list(PICKUP_TRANSITIONS.get(s.pickup_status, ())),
        }
        for s in rows
    ]
    if pickup_status in PICKUP_TRANSITIONS:
        out = [r for r in out if r["sale"].pickup_status == pickup_status]
    return out


def get_cancel_reasons():
    """Distinct list of cancellation reasons from shipping orders and voided sales."""
    ship = [
        r[0]
        for r in db.session.query(ShippingOrder.cancel_reason)
        .filter(ShippingOrder.cancel_reason != "")
        .distinct()
        .all()
    ]
    sales = [
        r[0]
        for r in db.session.query(Sale.cancel_reason)
        .filter(Sale.cancel_reason != "")
        .distinct()
        .all()
    ]
    return sorted(set(ship) | set(sales))


def get_cancelled_rows(start, end, reason="", search_text=""):
    """Combined timeline of cancelled shipments and voided sales invoices."""
    a, b = bounds(start, end)
    rows = []
    ship_query = (
        ShippingOrder.query.options(joinedload(ShippingOrder.sale))
        .filter_by(status="Cancelled")
        .filter(ShippingOrder.created_at >= a, ShippingOrder.created_at < b)
    )
    if reason:
        ship_query = ship_query.filter(ShippingOrder.cancel_reason == reason)
    for o in ship_query.order_by(ShippingOrder.id.desc()).all():
        rows.append(
            {
                "oid": o.id,
                "sale_id": o.sale_id,
                "customer_id": o.customer_id,
                "order": o.order_number,
                "invoice": o.sale.invoice if o.sale else "—",
                "customer": o.customer_name,
                "date": o.cancelled_at or o.updated_at or o.created_at,
                "reason": o.cancel_reason or "",
                "status": "Cancelled",
            }
        )
    sale_query = (
        Sale.query.filter_by(status="Voided")
        .filter(Sale.created_at >= a, Sale.created_at < b)
    )
    if reason:
        sale_query = sale_query.filter(Sale.cancel_reason == reason)
    for s in sale_query.order_by(Sale.id.desc()).all():
        rows.append(
            {
                "oid": None,
                "sale_id": s.id,
                "customer_id": s.customer_id,
                "order": s.invoice,
                "invoice": s.invoice,
                "customer": s.customer_name,
                "date": s.cancelled_at or s.created_at,
                "reason": s.cancel_reason or "",
                "status": "Voided",
            }
        )
    rows.sort(key=lambda r: str(r["date"] or ""), reverse=True)
    q = (search_text or "").strip()[:100].lower()
    if q:
        rows = [
            r
            for r in rows
            if q in r["order"].lower()
            or q in r["invoice"].lower()
            or q in r["customer"].lower()
        ]
    return rows


def get_return_rows(return_status, refund_status, start, end, search_text="", fallback_currency="EGP"):
    """Unified listing of returned shipping orders and refunded sales."""
    a, b = bounds(start, end)
    rows = []
    ship_query = (
        ShippingOrder.query.options(joinedload(ShippingOrder.sale))
        .filter_by(status="Returned")
        .filter(ShippingOrder.created_at >= a, ShippingOrder.created_at < b)
    )
    for o in ship_query.order_by(ShippingOrder.id.desc()).all():
        if return_status and o.status != return_status:
            continue
        sale = o.sale
        refund = sale.status if sale else "—"
        if refund_status and refund != refund_status:
            continue
        rows.append(
            {
                "oid": o.id,
                "sale_id": o.sale_id,
                "customer_id": o.customer_id,
                "order": o.order_number,
                "invoice": sale.invoice if sale else "—",
                "customer": o.customer_name,
                "phone": o.phone or "",
                "return_status": o.status,
                "refund_status": refund,
                "amount": sale.total if sale else 0,
                "currency": sale.currency if sale else fallback_currency,
                "date": o.updated_at or o.created_at,
            }
        )
    sale_query = (
        Sale.query.options(joinedload(Sale.customer))
        .filter_by(status="Refunded")
        .filter(Sale.created_at >= a, Sale.created_at < b)
    )
    if not (return_status and return_status != "—"):
        for s in sale_query.order_by(Sale.id.desc()).all():
            if refund_status and s.status != refund_status:
                continue
            rows.append(
                {
                    "oid": None,
                    "sale_id": s.id,
                    "customer_id": s.customer_id,
                    "order": s.invoice,
                    "invoice": s.invoice,
                    "customer": s.customer_name,
                    "phone": s.customer.phone if s.customer and s.customer.phone else "",
                    "return_status": "—",
                    "refund_status": s.status,
                    "amount": s.total,
                    "currency": s.currency,
                    "date": s.created_at,
                }
            )
    q = (search_text or "").strip()[:100].lower()
    if q:
        rows = [
            r
            for r in rows
            if q in r["order"].lower()
            or q in r["invoice"].lower()
            or q in r["customer"].lower()
            or q in (r["phone"] or "").lower()
        ]
    rows.sort(key=lambda r: str(r["date"] or ""), reverse=True)
    return rows
