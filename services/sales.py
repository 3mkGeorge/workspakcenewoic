"""Sales and purchasing transactions domain service for StorePro.

Encapsulates invoice creation, stock mutation on sales/reversals, purchase order
processing, and serialization of sale detail payloads for the modal/API.
"""

from datetime import timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import g
from models import (
    Customer,
    PICKUP_TRANSITIONS,
    Product,
    Purchase,
    PurchaseItem,
    Sale,
    SaleItem,
    Supplier,
    db,
    now,
)
from services.validation import cents, integer, required


def lines_from_form(form, purchase=False):
    """Validate and extract (Product, quantity, price/cost) lines from web form."""
    ids, quantities = form.getlist("product_id"), form.getlist("quantity")
    costs = form.getlist("unit_cost")
    if not ids or len(ids) > 100 or len(ids) != len(quantities):
        raise ValueError("Add between 1 and 100 products.")
    if purchase and len(costs) != len(ids):
        raise ValueError("Every purchase item needs a cost.")
    seen, lines = set(), []
    for i, pid in enumerate(ids):
        p = db.session.get(Product, integer(pid, 1))
        if not p or not p.active:
            raise ValueError("Choose an active product.")
        if p.id in seen:
            raise ValueError(
                "Each product can appear once; increase its quantity instead."
            )
        seen.add(p.id)
        lines.append(
            (p, integer(quantities[i], 1), cents(costs[i]) if purchase else p.price)
        )
    return lines


def next_number(model, prefix):
    """Generate the next unique invoice or purchase sequence number atomically."""
    n = (db.session.scalar(db.select(db.func.max(model.id))) or 0) + 1001
    while db.session.scalar(db.select(model.id).where(model.invoice == f"{prefix}{n}")):
        n += 1
    return f"{prefix}{n}"


def write_sale(form, existing=None):
    """Create or revise a standard form sale invoice, applying stock decrements and audits."""
    from services.core import audit, move, settings

    config = settings()
    if existing and (
        existing.status != "Completed"
        or existing.revision != integer(form.get("revision"), 1)
    ):
        raise ValueError("This invoice changed or cannot be edited. Reload it first.")
    lines = lines_from_form(form)
    cid = form.get("customer_id")
    customer = db.session.get(Customer, integer(cid, 1)) if cid else None
    if cid and (not customer or not customer.active):
        raise ValueError("Choose an active customer.")
    payment = form.get("payment")
    if payment not in ("Cash", "Card", "Bank Transfer", "Mobile Wallet"):
        raise ValueError("Choose a valid payment method.")
    subtotal = sum(q * price for _, q, price in lines)
    discount = cents(form.get("discount", "0"))
    if discount > subtotal:
        raise ValueError("Discount cannot exceed subtotal.")
    rate = (
        existing.tax_rate
        if existing
        else cents(config["tax_rate"])
        if config["tax_enabled"] == "1"
        else 0
    )
    tax = int(
        (Decimal(subtotal - discount) * rate / 10000).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    if existing:
        audit(
            "Invoice revision snapshot",
            json.dumps(
                {
                    "invoice": existing.invoice,
                    "revision": existing.revision,
                    "customer": existing.customer_name,
                    "payment": existing.payment,
                    "subtotal": existing.subtotal,
                    "discount": existing.discount,
                    "tax": existing.tax,
                    "total": existing.total,
                    "cost": existing.cost,
                    "items": [
                        {
                            "product_id": i.product_id,
                            "name": i.name,
                            "quantity": i.quantity,
                            "price": i.price,
                            "cost": i.cost,
                        }
                        for i in existing.items
                    ],
                },
                ensure_ascii=False,
            ),
        )
        for item in existing.items:
            move(item.product, item.quantity, "Sale edit reversal", existing.invoice)
        existing.items.clear()
        sale = existing
        sale.revision += 1
    else:
        sale = Sale(
            invoice=next_number(Sale, config["invoice_prefix"]),
            currency=config["currency"],
            user_id=g.user.id,
            cashier=g.user.name,
            token=required(form.get("token"), "Request token", 64),
            store_snapshot=json.dumps(
                {
                    k: config[k]
                    for k in (
                        "store_name",
                        "phone",
                        "email",
                        "address",
                        "receipt_header",
                        "receipt_footer",
                        "logo",
                    )
                }
            ),
        )
        db.session.add(sale)
    sale.customer_id = customer.id if customer else None
    sale.customer_name = customer.name if customer else "Walk-in Customer"
    sale.payment, sale.subtotal, sale.discount, sale.tax, sale.tax_rate = (
        payment,
        subtotal,
        discount,
        tax,
        rate,
    )
    sale.total, sale.cost, sale.note = (
        subtotal - discount + tax,
        sum(p.cost * q for p, q, _ in lines),
        form.get("note", "")[:500],
    )
    for p, q, price in lines:
        move(p, -q, "Sale", sale.invoice)
        sale.items.append(
            SaleItem(
                product_id=p.id,
                name=p.name,
                category_name=p.category.name,
                quantity=q,
                price=price,
                cost=p.cost,
            )
        )
    audit("Edit sale" if existing else "Create sale", sale.invoice)
    db.session.flush()
    return sale


def reverse_sale(sale, status):
    """Refund or void a completed sale, restoring inventory and logging audit."""
    from services.core import audit, move

    if sale.status != "Completed":
        raise ValueError("Only a completed invoice can be refunded or voided.")
    for item in sale.items:
        move(item.product, item.quantity, status, sale.invoice)
    sale.status = status
    sale.revision += 1
    audit(status, sale.invoice)


def refund_sale_items(sale, items_to_return):
    """Refund specific line items or quantities from a completed sale, restocking inventory."""
    from services.core import audit, move

    if sale.status != "Completed":
        raise ValueError("Only a completed invoice can be refunded.")

    if not items_to_return:
        raise ValueError("No items selected for return.")

    items_by_id = {item.id: item for item in sale.items}
    items_by_pid = {item.product_id: item for item in sale.items}

    total_existing_units = sum(i.quantity for i in sale.items)
    to_refund = []
    total_refund_units = 0

    for spec in items_to_return:
        item = None
        if "item_id" in spec and spec["item_id"] in items_by_id:
            item = items_by_id[spec["item_id"]]
        elif "product_id" in spec and spec["product_id"] in items_by_pid:
            item = items_by_pid[spec["product_id"]]
        if not item:
            continue
        try:
            qty = int(spec.get("quantity", 0))
        except (ValueError, TypeError):
            continue
        if qty <= 0:
            continue
        if qty > item.quantity:
            raise ValueError(
                f"Cannot return {qty} units of {item.name}; only {item.quantity} purchased."
            )
        to_refund.append((item, qty))
        total_refund_units += qty

    if not to_refund:
        raise ValueError("No valid items or quantities selected for refund.")

    if total_refund_units >= total_existing_units:
        reverse_sale(sale, "Refunded")
        return sale

    old_subtotal = sale.subtotal
    old_invoice_discount = max(0, sale.invoice_discount)
    details = []
    for item, qty in to_refund:
        move(item.product, qty, "Partial Refund", sale.invoice)
        details.append(f"{qty}x {item.name}")
        if qty == item.quantity:
            sale.items.remove(item)
            db.session.delete(item)
        else:
            remaining = item.quantity - qty
            item.discount = item.discount * remaining // item.quantity
            item.quantity = remaining

    # Same arithmetic as the POS: invoice discount pro-rated, VAT on the discounted net.
    sale.subtotal = sum(i.quantity * i.price for i in sale.items)
    invoice_discount = (
        old_invoice_discount * sale.subtotal // old_subtotal if old_subtotal else 0
    )
    sale.discount = min(sale.subtotal, sum(i.discount for i in sale.items) + invoice_discount)
    net = sale.subtotal - sale.discount
    sale.tax = int(
        (Decimal(net) * sale.tax_rate / 10000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    sale.total = net + sale.tax
    sale.cost = sum(i.cost * i.quantity for i in sale.items)
    sale.revision += 1

    note_text = f"[Partial refund: {', '.join(details)}]"
    if sale.note:
        sale.note = f"{sale.note} {note_text}"[:500]
    else:
        sale.note = note_text[:500]

    audit("Partial refund", f"{sale.invoice}: {', '.join(details)}")
    return sale


def receive_purchase(order):
    """Receive a pending purchase order, adjusting weighted average cost and adding stock."""
    from services.core import audit, move

    if order.status not in ("Pending", "Processing"):
        raise ValueError("This order cannot be received again.")
    for item in order.items:
        p = item.product
        p.cost = int(
            (
                Decimal(p.stock * p.cost + item.quantity * item.cost)
                / (p.stock + item.quantity)
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        db.session.flush()
        move(p, item.quantity, "Purchase", order.invoice)
    order.status = "Received"
    order.received_at = now()
    audit("Receive purchase", order.invoice)


def serialize_sale_detail(sale):
    """Format full sale detail payload for modal/API consumption with thumbnail resolution."""
    from services.product_media import primary_urls

    def cairo(value, time=False):
        if not value:
            return "—"
        try:
            value = value.replace(tzinfo=timezone.utc).astimezone(
                ZoneInfo("Africa/Cairo")
            )
        except ZoneInfoNotFoundError:
            value = value + timedelta(hours=3)
        fmt = "%d/%m/%Y" if g.settings.get("date_format") == "DD/MM/YYYY" else "%Y-%m-%d"
        return value.strftime(fmt + (" %I:%M %p" if time else ""))

    items = []
    for item in sale.items:
        try:
            _full, thumb = primary_urls(item.product) if item.product else ("", "")
        except Exception:
            thumb = ""
        items.append(
            {
                "id": item.id,
                "product_id": item.product_id,
                "image": thumb or "",
                "name": item.name,
                "quantity": item.quantity,
                "price": item.price,
                "discount": item.discount,
                "total": item.quantity * item.price - item.discount,
            }
        )

    return {
        "id": sale.id,
        "invoice": sale.invoice,
        "date": cairo(sale.created_at),
        "datetime": cairo(sale.created_at, True),
        "customer": sale.customer_name,
        "status": sale.status,
        "payment": sale.payment,
        "payments": [
            {"method": pay.method, "amount": pay.amount} for pay in sale.payments
        ],
        "user": sale.cashier,
        "items": items,
        "subtotal": sale.subtotal,
        "discount": sale.discount,
        "tax_rate": sale.tax_rate,
        "tax": sale.tax,
        "total": sale.total,
        "currency": sale.currency,
        "note": sale.note or "",
        "pickup_notes": sale.pickup_notes or "",
    }


def advance_pickup_order(sale, target):
    """Transition pickup status: Pending Pickup -> Ready For Pickup -> Collected."""
    from services.core import audit

    if sale.status != "Completed" or not sale.pickup_status:
        raise ValueError("Only active pickup orders have a pickup status.")
    allowed = PICKUP_TRANSITIONS.get(sale.pickup_status, ())
    if target not in allowed:
        raise ValueError(
            f"Cannot move {sale.invoice} from {sale.pickup_status} to {target or '—'}."
        )
    sale.pickup_status = target
    audit("Pickup status", f"{sale.invoice} → {target}")
    db.session.commit()
    return sale.pickup_status


def create_purchase_order(form):
    """Create a new purchase order with validated items, supplier, and optional instant receipt."""
    from services.core import audit

    supplier = db.get_or_404(Supplier, integer(form.get("supplier_id"), 1))
    if not supplier.active:
        raise ValueError("Choose an active supplier.")
    lines = lines_from_form(form, True)
    order = Purchase(
        invoice=next_number(Purchase, g.settings["purchase_prefix"]),
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        total=sum(q * c for p, q, c in lines),
        currency=g.settings["currency"],
        note=form.get("note", "")[:500],
        token=required(form.get("token"), "Request token", 64),
    )
    db.session.add(order)
    for p, q, c in lines:
        order.items.append(
            PurchaseItem(product_id=p.id, name=p.name, quantity=q, cost=c)
        )
    db.session.flush()
    audit("Create purchase", order.invoice)
    if form.get("receive") == "1":
        from services.permissions import require

        require("purchases.approve")
        receive_purchase(order)
    db.session.commit()
    return order
