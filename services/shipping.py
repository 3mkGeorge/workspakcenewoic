"""Delivery/shipping fulfillment helpers. Money stays in integer minor units."""

import json

from models import ShippingEvent, ShippingOrder, db, now
from services.core import audit

ADDRESS_FIELDS = (
    "customer_name",
    "phone",
    "alt_phone",
    "governorate",
    "city",
    "district",
    "landmark",
    "street",
    "building",
    "floor",
    "apartment",
    "postal_code",
    "notes",
)

# (field, label, max length, required for delivery)
ADDRESS_RULES = (
    ("customer_name", "Customer name", 120, True),
    ("phone", "Mobile number", 40, True),
    ("alt_phone", "Alternative mobile", 40, False),
    ("governorate", "Governorate", 80, True),
    ("city", "City", 80, True),
    ("district", "District", 80, False),
    ("landmark", "Landmark", 80, False),
    ("street", "Street address", 160, True),
    ("building", "Building number", 40, False),
    ("floor", "Floor", 20, False),
    ("apartment", "Apartment", 20, False),
    ("postal_code", "Postal code", 20, False),
    ("notes", "Delivery notes", 500, False),
)


def clean_address(raw):
    """Validate and normalize a delivery address dict from POS JSON."""
    if not isinstance(raw, dict):
        raise ValueError("Delivery address is missing.")
    cleaned = {}
    for field, label, limit, required in ADDRESS_RULES:
        value = raw.get(field, "")
        if not isinstance(value, str):
            raise ValueError(f"{label} must be text.")
        value = " ".join(value.split())
        if required and not value:
            raise ValueError(f"{label} is required for delivery.")
        if len(value) > limit:
            raise ValueError(f"{label} is too long.")
        cleaned[field] = value
    phone = cleaned["phone"].replace(" ", "").replace("-", "")
    if len(phone) < 7 or not phone.replace("+", "", 1).isdigit():
        raise ValueError("Enter a valid mobile number.")
    cleaned["phone"] = phone
    if cleaned["alt_phone"]:
        alt = cleaned["alt_phone"].replace(" ", "").replace("-", "")
        if len(alt) < 7 or not alt.replace("+", "", 1).isdigit():
            raise ValueError("Enter a valid alternative mobile number.")
        cleaned["alt_phone"] = alt
    return cleaned


def next_shipping_number():
    n = (db.session.scalar(db.select(db.func.max(ShippingOrder.id))) or 0) + 1001
    while db.session.scalar(
        db.select(ShippingOrder.id).where(ShippingOrder.order_number == f"SHP-{n}")
    ):
        n += 1
    return f"SHP-{n}"


def log_event(order, action, actor):
    db.session.add(ShippingEvent(order_id=order.id, action=action, actor=actor))


def ensure_invoice_active(order):
    if order.sale and order.sale.status != "Completed":
        raise ValueError(
            f"Invoice {order.sale.invoice} is {order.sale.status.lower()}. Cancel this shipment instead."
        )



def create_shipping_order(sale, address, courier="", shipping_cost=0):
    # No tracking code at creation: it is assigned when the shipment ships.
    order = ShippingOrder(
        order_number=next_shipping_number(),
        sale_id=sale.id,
        tracking_code=None,
        status="Pending",
        customer_id=sale.customer_id,
        user_id=sale.user_id,
        address_snapshot=json.dumps(address, ensure_ascii=False),
        shipping_cost=shipping_cost,
        courier=courier,
    )
    for field in ADDRESS_FIELDS:
        setattr(order, field, address.get(field, ""))
    db.session.add(order)
    db.session.flush()
    log_event(order, "Order Created", sale.cashier)
    audit("Create shipping order", f"{order.order_number} · {sale.invoice}")
    return order


def set_status(order, target, actor):
    from models import SHIPPING_TRANSITIONS, now

    if target not in SHIPPING_TRANSITIONS.get(order.status, ()):
        raise ValueError(
            f"Cannot move {order.order_number} from {order.status} to {target}."
        )
    order.status = target
    if target == "Cancelled":
        order.cancelled_at = now()
    log_event(order, target, actor)
    audit("Shipping status", f"{order.order_number} → {target}")


def address_lines(order):
    parts = [
        order.street,
        f"Building {order.building}" if order.building else "",
        f"Floor {order.floor}" if order.floor else "",
        f"Apt {order.apartment}" if order.apartment else "",
        order.landmark,
        order.district,
        order.city,
        order.governorate,
        order.postal_code,
    ]
    return ", ".join(p for p in parts if p)


def stats():
    """Dashboard + notification counters. All from one pass over open orders."""
    from datetime import timedelta

    now_ = now()
    orders = ShippingOrder.query.all()
    out = {
        "pending": 0,
        "out_for_delivery": 0,
        "delivered_today": 0,
        "returned": 0,
        "by_status": {},
        "stale_pending": [],
        "stale_transit": [],
        "returned_orders": [],
        "recent": [],
    }
    day_start = now_.replace(hour=0, minute=0, second=0, microsecond=0)
    for o in orders:
        out["by_status"][o.status] = out["by_status"].get(o.status, 0) + 1
        if o.status == "Pending":
            out["pending"] += 1
            if now_ - o.created_at > timedelta(hours=24):
                out["stale_pending"].append(o)
        elif o.status == "Out For Delivery":
            out["out_for_delivery"] += 1
            if now_ - (o.updated_at or o.created_at) > timedelta(hours=48):
                out["stale_transit"].append(o)
        elif o.status == "Delivered":
            if o.delivered_at and o.delivered_at >= day_start:
                out["delivered_today"] += 1
        elif o.status == "Returned":
            out["returned"] += 1
            out["returned_orders"].append(o)
        if now_ - o.created_at < timedelta(hours=24):
            out["recent"].append(o)
    for key in ("stale_pending", "stale_transit", "returned_orders", "recent"):
        out[key].sort(key=lambda o: o.id, reverse=True)
        out[key] = out[key][:10]
    return out


def report_rows(start, end):
    """Closed shipping reports for the analytics layer."""
    orders = (
        ShippingOrder.query.filter(
            ShippingOrder.created_at >= start, ShippingOrder.created_at < end
        )
        .order_by(ShippingOrder.id.desc())
        .all()
    )
    by_status, by_city, by_courier = {}, {}, {}
    delivered = returned = total = 0
    for o in orders:
        by_status[o.status] = by_status.get(o.status, 0) + 1
        by_city[o.city or "—"] = by_city.get(o.city or "—", 0) + 1
        key = o.courier or "Unassigned"
        row = by_courier.setdefault(key, {"orders": 0, "delivered": 0, "total": 0})
        row["orders"] += 1
        if o.status == "Delivered":
            delivered += 1
            row["delivered"] += 1
        if o.status == "Returned":
            returned += 1
        sale = o.sale
        row["total"] += sale.total if sale else 0
        total += 1
    success = round(100 * delivered / total, 1) if total else 0.0
    return {
        "orders": orders,
        "by_status": sorted(by_status.items(), key=lambda kv: -kv[1]),
        "by_city": sorted(by_city.items(), key=lambda kv: -kv[1]),
        "by_courier": sorted(by_courier.items(), key=lambda kv: -kv[1]["orders"]),
        "delivered": delivered,
        "returned": returned,
        "total": total,
        "success_rate": success,
    }


def clean_tracking_code(code, exclude_id=None):
    """Validate a manually entered tracking code (shared by edit + ship flows)."""
    if not isinstance(code, str):
        raise ValueError("Tracking code must be text.")
    code = code.strip().upper()[:40]
    if not code:
        raise ValueError("Tracking code cannot be empty.")
    other = ShippingOrder.query.filter_by(tracking_code=code).first()
    if other and other.id != exclude_id:
        raise ValueError("This tracking code is already used.")
    return code


def clean_tracking_url(url):
    """Optional courier tracking link."""
    import re
    if not isinstance(url, str):
        raise ValueError("Tracking URL must be text.")
    url = url.strip()[:300]
    if url and not re.match(r"https?://", url, re.IGNORECASE):
        raise ValueError("Tracking URL must start with http:// or https://.")
    return url


def serialize_order(order):
    """Serialize shipping order into dictionary format for frontend JSON API."""
    from flask import current_app, g
    sale = order.sale
    try:
        delivered_at = (
            current_app.jinja_env.filters["date"](order.delivered_at, True)
            if order.delivered_at
            else ""
        )
    except Exception:
        delivered_at = (
            order.delivered_at.isoformat(sep=" ", timespec="minutes")
            if order.delivered_at
            else ""
        )
    return {
        "id": order.id,
        "order_number": order.order_number,
        "invoice": sale.invoice if sale else "—",
        "sale_id": order.sale_id,
        "customer": (sale.customer_name if sale else "") or order.customer_name or "—",
        "phone": (
            sale.customer.phone
            if sale and sale.customer and sale.customer.phone
            else (order.phone or "")
        ),
        "city": order.city or "—",
        "total": sale.total if sale else 0,
        "currency": sale.currency if sale else g.settings.get("currency", "EGP"),
        "courier": order.courier or "—",
        "tracking_code": order.tracking_code or "",
        "tracking_url": order.tracking_url or "",
        "status": order.status,
        "created_at": order.created_at,
        "delivered_by": order.delivered_by or "",
        "delivered_at": delivered_at,
        "shipping_cost": order.shipping_cost,
        "shipping_billed": bool(sale and sale.shipping_charge),
        "shipment_date": order.shipment_date or "",
    }


def update_shipping_order_details(order, data, actor_name):
    """Update courier, tracking, address, cost, or shipment date with event logging."""
    from datetime import datetime
    from models import SHIPPING_TRANSITIONS

    if order.status == "Delivered":
        raise ValueError("Delivered shipments are locked and cannot be edited.")
    if not SHIPPING_TRANSITIONS.get(order.status):
        raise ValueError(f"{order.status} shipments are closed and cannot be edited.")

    changed = []
    if "courier" in data:
        courier = data["courier"]
        if not isinstance(courier, str):
            raise ValueError("Courier must be text.")
        courier = courier.strip()[:80]
        if courier == "—":
            courier = ""  # the display placeholder for "no courier" is not a courier name
        if courier != order.courier:
            order.courier = courier
            changed.append(f"courier {courier or '—'}")
            log_event(order, f"Courier set to {courier or '—'}", actor_name)

    if "tracking_code" in data:
        code = clean_tracking_code(data["tracking_code"], exclude_id=order.id)
        had_code = bool(order.tracking_code)
        if code != (order.tracking_code or ""):
            order.tracking_code = code
            changed.append("tracking code")
            log_event(
                order,
                "Tracking code updated" if had_code else "Tracking code added",
                actor_name,
            )

    if "tracking_url" in data:
        url = clean_tracking_url(data["tracking_url"])
        if url != (order.tracking_url or ""):
            order.tracking_url = url
            changed.append("tracking URL")
            log_event(order, "Tracking URL updated", actor_name)

    address_limits = {
        "governorate": 80,
        "city": 80,
        "district": 80,
        "landmark": 80,
        "street": 160,
        "building": 40,
        "floor": 20,
        "apartment": 20,
        "postal_code": 20,
    }
    address_touched = False
    for field, limit in address_limits.items():
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, str):
            raise ValueError(f"{field.replace('_', ' ').title()} must be text.")
        value = " ".join(value.split())[:limit]
        if not value and field in ("governorate", "city", "street"):
            raise ValueError(f"{field.title()} is required for delivery.")
        if value != (getattr(order, field) or ""):
            setattr(order, field, value)
            address_touched = True

    if address_touched:
        changed.append("delivery address")
        log_event(order, "Delivery address updated", actor_name)

    if "shipping_cost" in data:
        cost = data["shipping_cost"]
        if isinstance(cost, bool) or not isinstance(cost, int):
            raise ValueError("Shipping cost must be a whole number.")
        if cost < 0 or cost > 1000000000:
            raise ValueError("Shipping cost is out of range.")
        if cost != order.shipping_cost:
            if order.sale is not None and order.sale.shipping_charge:
                # The fee is part of the invoice total and its payments; changing it
                # here would make the shipment and the invoice disagree.
                raise ValueError(
                    f"The shipping fee is billed on invoice {order.sale.invoice} and cannot be changed here."
                )
            order.shipping_cost = cost
            changed.append("shipping cost")
            log_event(order, "Shipping cost updated", actor_name)

    if "shipment_date" in data:
        date = data["shipment_date"]
        if not isinstance(date, str):
            raise ValueError("Shipment date must be text.")
        date = date.strip()[:10]
        if date:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                raise ValueError("Shipment date must look like YYYY-MM-DD.")
        if date != order.shipment_date:
            order.shipment_date = date
            changed.append("shipment date")
            log_event(order, "Shipment date updated", actor_name)

    ship = data.get("ship") is True
    if ship and not order.tracking_code:
        raise ValueError("Enter the tracking code provided by the courier before marking as Shipped.")
    if ship or (order.status == "Ready For Shipment" and "tracking code" in changed):
        ensure_invoice_active(order)
        set_status(order, "Shipped", actor_name)
        changed.append("status Shipped")
    if changed:
        audit("Update shipping order", f"{order.order_number}: {', '.join(changed)}")
        db.session.commit()

    return changed


def execute_order_transition(order, target, data, actor_name):
    """Validate and transition shipping order status with courier and event rules."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    from models import SHIPPING_TRANSITIONS

    if target not in SHIPPING_TRANSITIONS:
        raise ValueError("Unknown shipping status.")
    if target not in ("Cancelled", "Returned"):
        ensure_invoice_active(order)

    if target == "Cancelled":
        reason = data.get("cancel_reason", "")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A cancellation reason is required.")
        order.cancel_reason = reason.strip()[:200]

    if target == "Shipped":
        if data.get("generate_tracking"):
            raise ValueError(
                "Tracking codes are provided by the courier company. "
                "Enter the code instead of generating one."
            )
        if data.get("tracking_code"):
            order.tracking_code = clean_tracking_code(
                data["tracking_code"], exclude_id=order.id
            )
            log_event(order, "Tracking code added", actor_name)
        if not order.tracking_code:
            raise ValueError(
                "Enter the tracking code provided by the courier "
                "before marking as Shipped."
            )

    if target == "Delivered":
        by = data.get("delivered_by", "")
        date = data.get("delivered_date", "")
        time = data.get("delivered_time", "")
        if not isinstance(by, str) or not by.strip():
            raise ValueError("Delivered By is required.")
        if not isinstance(date, str) or not date.strip():
            raise ValueError("Delivered Date is required.")
        if not isinstance(time, str) or not time.strip():
            raise ValueError("Delivered Time is required.")
        try:
            at = datetime.strptime(f"{date.strip()} {time.strip()}", "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError("Delivered date/time must look like YYYY-MM-DD HH:MM.")
        # Entered in store-local time; stored as naive UTC like every other timestamp.
        at = at.replace(tzinfo=ZoneInfo("Africa/Cairo")).astimezone(timezone.utc).replace(tzinfo=None)
        if at > now().replace(microsecond=0) + timedelta(minutes=5):
            raise ValueError("Delivered time cannot be in the future.")
        order.delivered_by = by.strip()[:120]
        order.delivered_at = at

    set_status(order, target, actor_name)
    db.session.commit()
    return order

