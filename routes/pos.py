import secrets
from datetime import timedelta
from flask import Blueprint, g, request, render_template, jsonify, url_for, current_app
from sqlalchemy import case
from models import db, Product, Sale, SaleItem, Customer, now
from services.core import required, audit, integer
from services.pos import calculate, save_invoice, product_json, edit_sale, METHODS

pos = Blueprint("pos", __name__, url_prefix="/api/pos")


def render_pos(sale=None):
    from services.core import cents

    initial = None
    if sale:
        fulfillment = None
        shipping = getattr(sale, "shipping", None)
        if shipping is not None:
            fulfillment = {
                "method": "delivery",
                "summary": f"Shipping {shipping.order_number} · {shipping.status}",
            }
        elif sale.pickup_date or sale.pickup_notes:
            fulfillment = {
                "method": "pickup",
                "summary": " · ".join(
                    p for p in (sale.pickup_date, sale.pickup_notes) if p
                ),
            }
        initial = {
            "sale_id": sale.id,
            "revision": sale.revision,
            "invoice": sale.invoice,
            "fulfillment": fulfillment,
            "items": [
                {
                    "product": product_json(i.product, sale),
                    "quantity": i.quantity,
                    "discount": i.discount,
                }
                for i in sale.items
            ],
            "customer": (
                {"id": sale.customer_id, "name": sale.customer_name}
                if sale.customer_id
                else None
            ),
            "invoice_discount": sale.invoice_discount,
            "note": sale.note,
            "payments": [
                {"method": p.method, "amount": p.amount} for p in sale.payments
            ],
        }
    from models import COURIER_PROVIDERS, ShippingOrder

    data = {
        "user_id": g.user.id,
        "currency": sale.currency if sale else g.settings["currency"],
        "tax_rate": sale.tax_rate
        if sale
        else cents(g.settings["tax_rate"])
        if g.settings["tax_enabled"] == "1"
        else 0,
        "store": g.settings["store_name"],
        "language": g.settings["language"],
        "token": secrets.token_hex(24),
        "initial": initial,
        "methods": METHODS,
        "couriers": sorted(
            {
                c[0]
                for c in db.session.query(ShippingOrder.courier)
                .filter(ShippingOrder.courier != "")
                .distinct()
                .all()
            }
            | set(COURIER_PROVIDERS)
        ),
        "draft_scope": str(g.user.id)
        + ":"
        + str(g.user.version)
        + ":"
        + (str(sale.id) if sale else "new"),
    }
    return render_template(
        "sales/pos.html", title="Edit Sale" if sale else "New Sale", pos_config=data
    )


def payload():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("Send a valid invoice JSON object.")
    return value


def editing():
    sid = request.args.get("editing")
    return edit_sale(integer(sid, 1)) if sid else None


@pos.get("/products")
def products():
    sale = editing()
    query = Product.query.filter_by(active=True)
    q = request.args.get("q", "").strip()[:160]
    barcode = request.args.get("barcode", "").strip()[:80]
    ids = request.args.get("ids")
    if ids:
        values = ids.split(",")
        if len(values) > 100:
            raise ValueError("Too many products.")
        query = Product.query.filter(Product.id.in_([integer(v, 1) for v in values]))
    elif barcode:
        query = query.filter(Product.barcode == barcode)
    elif q:
        query = query.filter(
            db.or_(
                Product.name.contains(q, autoescape=True),
                Product.sku.contains(q, autoescape=True),
                Product.barcode.contains(q, autoescape=True),
            )
        )
    cursor = integer(request.args.get("offset", "0"), 0, 1000000)
    limit = 16
    rows = (
        query.order_by(
            case((Product.barcode == q, 0), (Product.sku == q, 1), else_=2),
            Product.name,
            Product.id,
        )
        .offset(cursor)
        .limit(limit + 1 if not ids else 101)
        .all()
    )
    return jsonify(
        items=[product_json(p, sale) for p in rows[:limit] if not ids]
        if not ids
        else [product_json(p, sale) for p in rows],
        next_offset=cursor + limit if len(rows) > limit and not ids else None,
    )


@pos.get("/shortcuts")
def shortcuts():
    sale = editing()
    base = (
        db.select(SaleItem.product_id)
        .join(Sale)
        .where(
            Sale.status == "Completed", Sale.created_at >= now() - timedelta(days=90)
        )
        .group_by(SaleItem.product_id)
    )
    frequent = list(
        db.session.scalars(
            base.order_by(db.func.sum(SaleItem.quantity).desc()).limit(8)
        )
    )
    recent = list(
        db.session.scalars(base.order_by(db.func.max(Sale.created_at).desc()).limit(8))
    )
    products = {
        p.id: p
        for p in db.session.scalars(
            db.select(Product).where(
                Product.id.in_(set(frequent + recent)), Product.active == True
            )
        )
    }
    return jsonify(
        frequent=[product_json(products[i], sale) for i in frequent if i in products],
        recent=[product_json(products[i], sale) for i in recent if i in products],
    )


@pos.get("/customers")
def customers():
    q = request.args.get("q", "").strip()[:120]
    rows = (
        Customer.query.filter(
            Customer.active == True,
            db.or_(
                Customer.name.contains(q, autoescape=True),
                Customer.phone.contains(q, autoescape=True),
            ),
        )
        .order_by(Customer.name, Customer.id)
        .limit(20)
        .all()
    )
    return jsonify(items=[{"id": c.id, "name": c.name, "phone": c.phone} for c in rows])


@pos.post("/customers")
def new_customer():
    data = payload()
    for key in ("name", "phone", "email", "address"):
        if not isinstance(data.get(key, ""), str):
            raise ValueError("Customer fields must be text.")
    name = required(data.get("name"), "Customer name", 120)
    phone = data.get("phone", "").strip()
    email = data.get("email", "").strip()
    address = data.get("address", "").strip()
    if len(phone) > 40 or len(email) > 120 or len(address) > 300:
        raise ValueError("Customer contact details are too long.")
    if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
        raise ValueError("Enter a valid email address.")
    c = Customer(name=name, phone=phone, email=email, address=address)
    db.session.add(c)
    audit("Add customer from POS", name)
    db.session.commit()
    return jsonify(id=c.id, name=c.name, phone=c.phone), 201


@pos.post("/quote")
def quote():
    data = payload()
    sale = edit_sale(data.get("sale_id"))
    if sale is None and isinstance(data.get("token"), str):
        confirmed = Sale.query.filter_by(token=data["token"], user_id=g.user.id).first()
        if confirmed:
            return jsonify(saved_invoice=sale_response(confirmed))
    return jsonify(calculate(data, sale))


def sale_response(sale):
    return dict(
        id=sale.id,
        invoice=sale.invoice,
        total=sale.total,
        currency=sale.currency,
        detail_url=url_for("transactions.sales", selected=sale.id),
        invoice_url=url_for("transactions.invoice", sid=sale.id),
        receipt_url=url_for("transactions.invoice", sid=sale.id, receipt=1),
    )


@pos.post("/sales")
def save():
    data = payload()
    with current_app.config["DB_LOCK"]:
        sale = save_invoice(data, edit_sale(data.get("sale_id")))
        db.session.commit()
    return jsonify(sale_response(sale))
