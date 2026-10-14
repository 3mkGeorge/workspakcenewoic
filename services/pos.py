"""POS calculations use integer piastres. Server prices and stock are authoritative."""

import json
import re
from decimal import Decimal, ROUND_HALF_UP
from flask import g, url_for
from models import db, Product, Customer, Sale, SaleItem, SalePayment
from services.core import audit, move, next_number, cents

METHODS = ("Cash", "Visa", "Mastercard", "Bank Transfer", "Wallet")
MAX_MONEY = 1_000_000_000_000


def whole(value, label, minimum=0, maximum=MAX_MONEY):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(
            f"{label} must be a whole number between {minimum} and {maximum}."
        )
    return value


def edit_sale(sid):
    if sid is None:
        return None
    whole(sid, "Invoice ID", 1)
    from services.permissions import require
    require("sales.edit")
    sale = db.get_or_404(Sale, sid)
    if sale.status != "Completed":
        raise ValueError("Only completed invoices can be edited.")
    return sale


def product_json(product, sale=None):
    previous = (
        next((i for i in sale.items if i.product_id == product.id), None)
        if sale
        else None
    )
    try:
        from services.product_media import primary_urls

        full, thumb = primary_urls(product)
    except Exception:
        full, thumb = "", ""
    if not full and getattr(product, "image", None):
        full = url_for("static", filename="uploads/" + product.image)
        thumb = full
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "barcode": product.barcode or "",
        "price": previous.price if previous else product.price,
        "cost": previous.cost if previous else product.cost,
        "stock": product.stock + (previous.quantity if previous else 0),
        "minimum": product.minimum,
        "active": product.active,
        "image": full,
        "thumb": thumb or full,
    }


def calculate(payload, sale=None):
    raw = payload.get("items", [])
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("An invoice may contain at most 100 products.")
    merged = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Invalid invoice item.")
        pid = whole(item.get("product_id"), "Product ID", 1)
        quantity = whole(item.get("quantity"), "Quantity", 1, 1_000_000)
        discount = whole(item.get("discount", 0), "Line discount")
        expected = whole(item.get("unit_price"), "Unit price")
        if pid not in merged:
            merged[pid] = {"quantity": 0, "discount": 0, "expected": expected}
        if merged[pid]["expected"] != expected:
            raise ValueError("Duplicate product prices disagree.")
        merged[pid]["quantity"] += quantity
        merged[pid]["discount"] += discount
        whole(merged[pid]["quantity"], "Quantity", 1, 1_000_000)
    products = (
        {
            p.id: p
            for p in db.session.scalars(
                db.select(Product).where(Product.id.in_(merged))
            )
        }
        if merged
        else {}
    )
    lines, issues = [], []
    subtotal = line_discounts = cost = 0
    for pid, values in merged.items():
        p = products.get(pid)
        if not p:
            raise ValueError("A product no longer exists. Remove it from the draft.")
        data = product_json(p, sale)
        q, discount = values["quantity"], values["discount"]
        if not p.active:
            issues.append(f"{p.name} is no longer active.")
        if q > data["stock"]:
            issues.append(f"{p.name}: only {data['stock']} available.")
        if values["expected"] != data["price"]:
            issues.append(
                f"{p.name}: the selling price changed. Review the updated price."
            )
        gross = data["price"] * q
        whole(gross, "Line total")
        if discount > gross:
            issues.append(f"{p.name}: discount exceeds the line value.")
        subtotal += gross
        line_discounts += discount
        cost += data["cost"] * q
        lines.append(
            {
                "product": data,
                "quantity": q,
                "discount": discount,
                "total": max(0, gross - discount),
            }
        )
    invoice_discount = whole(payload.get("invoice_discount", 0), "Invoice discount")
    discount = line_discounts + invoice_discount
    if discount > subtotal:
        issues.append("Discount cannot exceed the subtotal.")
    whole(subtotal, "Subtotal")
    rate = (
        sale.tax_rate
        if sale
        else cents(g.settings["tax_rate"])
        if g.settings["tax_enabled"] == "1"
        else 0
    )
    net = max(0, subtotal - discount)
    tax = int(
        (Decimal(net) * rate / 10000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    profit = net - cost
    return {
        "items": lines,
        "subtotal": subtotal,
        "line_discount": line_discounts,
        "invoice_discount": invoice_discount,
        "discount": discount,
        "tax_rate": rate,
        "tax": tax,
        "total": net + tax,
        "cost": cost,
        "profit": profit,
        "margin": round(profit * 100 / net, 2) if net else 0,
        "currency": sale.currency if sale else g.settings["currency"],
        "issues": issues,
        "valid": bool(lines) and not issues,
    }


def parse_payments(raw, total):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 5:
        raise ValueError("Choose between one and five payment methods.")
    merged = {}
    for row in raw:
        if not isinstance(row, dict) or row.get("method") not in METHODS:
            raise ValueError("Choose a valid payment method.")
        amount = whole(row.get("amount"), "Payment amount")
        if amount == 0 and total != 0:
            raise ValueError("Each payment must be greater than zero.")
        merged[row["method"]] = merged.get(row["method"], 0) + amount
    if sum(merged.values()) != total:
        raise ValueError("Split payments must add up exactly to the invoice total.")
    return merged


def save_invoice(payload, sale=None):
    token = payload.get("token", "")
    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32,64}", token):
        raise ValueError(
            "Invalid invoice request token. Restore the draft after refreshing."
        )
    duplicate = Sale.query.filter_by(token=token).first() if not sale else None
    if duplicate:
        if duplicate.user_id != g.user.id:
            raise ValueError("Request token belongs to another user.")
        return duplicate
    is_new = sale is None
    if sale and whole(payload.get("revision"), "Revision", 1) != sale.revision:
        raise ValueError(
            "This invoice changed in another session. Reopen it before editing."
        )
    quote = calculate(payload, sale)
    if not quote["valid"]:
        raise ValueError(" ".join(quote["issues"]) or "Add at least one product.")
    if (
        payload.get("tax_rate") != quote["tax_rate"]
        or payload.get("currency") != quote["currency"]
    ):
        raise ValueError(
            "Tax or currency changed. Refresh the invoice totals before saving."
        )
    payments = parse_payments(payload.get("payments"), quote["total"])
    cid = payload.get("customer_id")
    customer = (
        db.session.get(Customer, whole(cid, "Customer ID", 1))
        if cid is not None
        else None
    )
    if cid is not None and (not customer or not customer.active):
        raise ValueError("Choose an active customer.")
    note = payload.get("note", "")
    if not isinstance(note, str) or len(note) > 500:
        raise ValueError("Notes may contain up to 500 characters.")
    if sale:
        audit(
            "Invoice revision snapshot",
            json.dumps(
                {
                    "invoice": sale.invoice,
                    "revision": sale.revision,
                    "subtotal": sale.subtotal,
                    "discount": sale.discount,
                    "tax": sale.tax,
                    "total": sale.total,
                    "cost": sale.cost,
                    "customer": sale.customer_name,
                    "payment": sale.payment,
                    "items": [
                        {
                            "product_id": i.product_id,
                            "name": i.name,
                            "quantity": i.quantity,
                            "price": i.price,
                            "cost": i.cost,
                            "discount": i.discount,
                        }
                        for i in sale.items
                    ],
                    "payments": [
                        {"method": p.method, "amount": p.amount} for p in sale.payments
                    ],
                },
                ensure_ascii=False,
            ),
        )
        for item in sale.items:
            move(item.product, item.quantity, "Sale edit reversal", sale.invoice)
        sale.items.clear()
        sale.payments.clear()
        db.session.flush()
        sale.revision += 1
    else:
        sale = Sale(
            invoice=next_number(Sale, g.settings["invoice_prefix"]),
            user_id=g.user.id,
            cashier=g.user.name,
            token=token,
            currency=quote["currency"],
            store_snapshot=json.dumps(
                {
                    k: g.settings[k]
                    for k in (
                        "store_name",
                        "phone",
                        "email",
                        "address",
                        "receipt_header",
                        "receipt_footer",
                        "logo",
                    )
                },
                ensure_ascii=False,
            ),
        )
        db.session.add(sale)
    sale.customer_id = customer.id if customer else None
    sale.customer_name = customer.name if customer else "Walk-in Customer"
    sale.payment = next(iter(payments)) if len(payments) == 1 else "Split"
    sale.subtotal, sale.discount, sale.tax, sale.tax_rate = (
        quote["subtotal"],
        quote["discount"],
        quote["tax"],
        quote["tax_rate"],
    )
    sale.total, sale.cost, sale.note = quote["total"], quote["cost"], note
    for line in quote["items"]:
        data = line["product"]
        product = db.session.get(Product, data["id"])
        move(product, -line["quantity"], "Sale", sale.invoice)
        sale.items.append(
            SaleItem(
                product_id=product.id,
                name=product.name,
                category_name=product.category.name,
                quantity=line["quantity"],
                price=data["price"],
                cost=data["cost"],
                discount=line["discount"],
            )
        )
    for method, amount in payments.items():
        sale.payments.append(SalePayment(method=method, amount=amount))
    apply_fulfillment(payload, sale, is_new)
    audit("Save POS invoice", sale.invoice)
    db.session.flush()
    return sale


def apply_fulfillment(payload, sale, is_new):
    """Persist store-pickup or delivery data for a newly saved invoice.

    Fulfillment is locked at creation: edits via revision never touch it,
    so shipping history stays append-only like the ledger itself.
    `is_new` is passed by the caller because autoflush may already have
    assigned sale.id by the time this runs.
    """
    from services.shipping import clean_address, create_shipping_order

    if not is_new:
        return
    data = payload.get("fulfillment")
    if not isinstance(data, dict):
        return
    method = data.get("method", "pickup")
    if method not in ("pickup", "delivery"):
        raise ValueError("Choose Store Pickup or Delivery.")
    if method == "pickup":
        date = data.get("pickup_date", "")
        if not isinstance(date, str):
            raise ValueError("Pickup date must be text.")
        date = date.strip()[:10]
        if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("Pickup date must look like YYYY-MM-DD.")
        notes = data.get("pickup_notes", "")
        if not isinstance(notes, str):
            raise ValueError("Pickup notes must be text.")
        sale.pickup_date = date
        sale.pickup_notes = notes.strip()[:300]
        sale.pickup_status = "Pending Pickup"
        return
    address = clean_address(data.get("address"))
    courier = data.get("courier", "")
    if not isinstance(courier, str):
        raise ValueError("Courier must be text.")
    courier = courier.strip()[:80]
    cost = data.get("shipping_cost", 0)
    if isinstance(cost, bool) or not isinstance(cost, int):
        raise ValueError("Shipping cost must be a whole number.")
    if cost < 0 or cost > 1000000000:
        raise ValueError("Shipping cost is out of range.")
    if data.get("update_profile") and sale.customer_id:
        from services.permissions import require

        # Same rule as the Customers page: changing a customer's contact
        # details needs customers.edit, whichever screen asks for it.
        require("customers.edit")
        customer = db.session.get(Customer, sale.customer_id)
        if customer and customer.active:
            if address["phone"]:
                customer.phone = address["phone"]
            street = ", ".join(
                p
                for p in (
                    address["street"],
                    address["district"],
                    address["city"],
                    address["governorate"],
                )
                if p
            )
            if street:
                customer.address = street[:300]
    create_shipping_order(sale, address, courier=courier, shipping_cost=cost)
