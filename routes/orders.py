"""Orders hub: shipping / pickup / cancelled / returns tabs.

Read-only views over existing sales + shipping data (no new tables).
Invoice remains the owner of products, prices, VAT, discounts and totals;
the hub only surfaces fulfillment state: shipping, pickup, cancellation,
returns and refunds.
"""

from flask import Blueprint, g, render_template, request

from models import SHIPPING_TRANSITIONS, Sale, ShippingOrder
from routes.shipping import COURIER_PROVIDERS, STATUS_BADGES, shipping_listing
from services.analytics import date_range
from services.orders import (
    OPEN_SHIPPING,
    TERMINAL_SALES,
    get_cancel_reasons,
    get_cancelled_rows,
    get_orders_hub_counters,
    get_pickup_rows,
    get_return_rows,
)

orders_hub = Blueprint("orders_hub", __name__)

TABS = ("shipping", "pickup", "cancelled", "returns")
STATUS_MAP = {
    "pending": "Pending",
    "packed": "Packed",
    "ready": "Ready For Shipment",
    "shipped": "Shipped",
    "out_for_delivery": "Out For Delivery",
    "delivered": "Delivered",
}
FULFILLMENT_PIPELINE = [
    ("all", "All"),
    ("pickup", "Pickup"),
    ("pending", "Pending"),
    ("packed", "Packed"),
    ("ready", "Ready"),
    ("shipped", "Shipped"),
    ("out_for_delivery", "Out For Delivery"),
    ("delivered", "Delivered"),
    ("returned", "Returned"),
    ("cancelled", "Cancelled"),
]


@orders_hub.get("/orders")
def hub():
    tab = request.args.get("tab", "shipping")
    # Normalize aliases
    if tab == "returned":
        tab = "returns"
    if tab not in TABS and tab not in STATUS_MAP and tab != "all":
        tab = "shipping"
    start, end = date_range()
    search_q = request.args.get("q", "").strip()
    counters = get_orders_hub_counters()
    ctx = {
        "title": "Fulfillment & Orders",
        "tab": tab,
        "tabs": TABS,
        "pipeline": FULFILLMENT_PIPELINE,
        "counters": counters,
        "start": start,
        "end": end,
    }
    if tab in ("shipping", "all") or tab in STATUS_MAP:
        if tab == "packed":
            base = ShippingOrder.query.filter(
                ShippingOrder.status.in_(("Packed", "Preparing"))
            )
        elif tab in STATUS_MAP:
            base = ShippingOrder.query.filter_by(status=STATUS_MAP[tab])
        elif tab == "all":
            base = ShippingOrder.query
        else:
            base = (
                ShippingOrder.query.join(Sale, ShippingOrder.sale_id == Sale.id).filter(
                    ShippingOrder.status.in_(OPEN_SHIPPING),
                    Sale.status.notin_(TERMINAL_SALES),
                )
            )
        page, cities, couriers = shipping_listing(base_query=base)
        ctx.update(
            page=page,
            statuses=list(SHIPPING_TRANSITIONS),
            badges=STATUS_BADGES,
            transitions=SHIPPING_TRANSITIONS,
            cities=cities,
            couriers=couriers,
            shipping_couriers=list(COURIER_PROVIDERS),
        )
    elif tab == "pickup":
        pickup_status = request.args.get("pickup_status", "")
        ctx.update(
            pickup_status=pickup_status,
            pickup_rows=get_pickup_rows(pickup_status, start, end, search_text=search_q),
        )
    elif tab == "cancelled":
        cancel_reason = request.args.get("cancel_reason", "")
        ctx.update(
            cancel_reason=cancel_reason,
            cancel_reasons=get_cancel_reasons(),
            cancelled_rows=get_cancelled_rows(
                start, end, reason=cancel_reason, search_text=search_q
            ),
        )
    else:
        return_status = request.args.get("return_status", "")
        refund_status = request.args.get("refund_status", "")
        ctx.update(
            return_status=return_status,
            refund_status=refund_status,
            return_rows=get_return_rows(
                return_status,
                refund_status,
                start,
                end,
                search_text=search_q,
                fallback_currency=g.settings["currency"],
            ),
        )
    return render_template("orders/index.html", **ctx)
