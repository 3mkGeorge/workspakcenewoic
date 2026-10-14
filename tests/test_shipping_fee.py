"""Shipping fee is a real invoice charge.

Store policy (confirmed): invoice total = (products − discounts) + VAT on products
+ shipping fee. The fee carries no VAT, is never discounted and is counted once.
A partial refund keeps the fee billed; a full refund or void reverses the whole
invoice. Partial refunds reduce the last-entered payment method first.
"""

import io
import re

from test_app import app, backup_response, client, finish_restore  # noqa: F401
from models import InventoryMovement, Product, Sale, SalePayment, ShippingOrder, db

FEE = 5000  # 50.00 EGP


def pos(**changes):
    data = dict(
        token="a" * 48,
        items=[dict(product_id=1, quantity=1, discount=0, unit_price=10000)],
        invoice_discount=0,
        customer_id=1,
        note="",
        tax_rate=1400,
        currency="EGP",
        payments=[dict(method="Cash", amount=11400 + FEE)],
        fulfillment={
            "method": "delivery",
            "address": {
                "customer_name": "Fee Customer",
                "phone": "+201001234567",
                "governorate": "Cairo",
                "city": "Nasr City",
                "street": "1 Fee St",
            },
            "courier": "Bosta",
            "shipping_cost": FEE,
        },
    )
    data.update(changes)
    return data


def money(cents):
    return f"{cents / 100:,.2f}"


# 1 -------------------------------------------------------------------------------
def test_delivery_sale_persists_fee_in_total_and_payments(app, client):
    r = client.post("/api/pos/sales", json=pos())
    assert r.status_code == 200, r.json
    assert r.json["total"] == 16400
    with app.app_context():
        sale = Sale.query.one()
        assert (sale.subtotal, sale.discount, sale.tax, sale.total) == (10000, 0, 1400, 16400)
        assert sale.shipping_charge == FEE
        assert sum(p.amount for p in sale.payments) == sale.total
        assert ShippingOrder.query.one().shipping_cost == FEE


# 2 -------------------------------------------------------------------------------
def test_sales_without_shipping_are_unchanged(app, client):
    pickup = pos(fulfillment={"method": "pickup"}, payments=[dict(method="Cash", amount=11400)])
    assert client.post("/api/pos/sales", json=pickup).status_code == 200
    walk_in = pos(token="b" * 48, customer_id=None, payments=[dict(method="Cash", amount=11400)])
    walk_in.pop("fulfillment")
    assert client.post("/api/pos/sales", json=walk_in).status_code == 200
    free = pos(token="c" * 48, payments=[dict(method="Cash", amount=11400)])
    free["fulfillment"]["shipping_cost"] = 0
    assert client.post("/api/pos/sales", json=free).status_code == 200
    with app.app_context():
        for sale in Sale.query.all():
            assert (sale.total, sale.shipping_charge) == (11400, 0)


# 3 -------------------------------------------------------------------------------
def test_discounts_and_vat_apply_to_products_only(app, client):
    data = pos(
        items=[dict(product_id=1, quantity=2, discount=1000, unit_price=10000)],
        invoice_discount=500,
        payments=[dict(method="Cash", amount=26090)],
    )
    # subtotal 200.00 − discounts 15.00 = 185.00; VAT 14% = 25.90; + fee 50.00 = 260.90
    quote = client.post("/api/pos/quote", json=data).json
    assert (quote["subtotal"], quote["discount"], quote["tax"], quote["shipping"], quote["total"]) == (
        20000, 1500, 2590, FEE, 26090,
    )
    assert client.post("/api/pos/sales", json=data).status_code == 200
    # A discount larger than the products cannot eat into the shipping fee.
    over = pos(token="d" * 48, invoice_discount=10001, payments=[dict(method="Cash", amount=FEE)])
    r = client.post("/api/pos/sales", json=over)
    assert r.status_code == 400 and "Discount cannot exceed" in r.json["error"]


# 4 -------------------------------------------------------------------------------
def test_cash_payment_must_cover_the_fee(app, client):
    short = pos(payments=[dict(method="Cash", amount=11400)])
    r = client.post("/api/pos/sales", json=short)
    assert r.status_code == 400 and "add up exactly" in r.json["error"]
    with app.app_context():
        assert Sale.query.count() == 0 and ShippingOrder.query.count() == 0
        assert db.session.get(Product, 1).stock == 10
    assert client.post("/api/pos/sales", json=pos()).status_code == 200


# 5 -------------------------------------------------------------------------------
def test_split_payments_balance_against_total_with_fee(app, client):
    wrong = pos(payments=[dict(method="Cash", amount=10000), dict(method="Visa", amount=1400)])
    assert client.post("/api/pos/sales", json=wrong).status_code == 400
    right = pos(payments=[dict(method="Cash", amount=10000), dict(method="Visa", amount=6400)])
    assert client.post("/api/pos/sales", json=right).status_code == 200
    with app.app_context():
        sale = Sale.query.one()
        assert sale.payment == "Split" and sorted(p.amount for p in sale.payments) == [6400, 10000]


# 6 -------------------------------------------------------------------------------
def test_editing_a_delivery_sale_never_adds_the_fee_twice(app, client):
    sid = client.post("/api/pos/sales", json=pos()).json["id"]
    edit = pos(
        sale_id=sid,
        revision=1,
        items=[dict(product_id=1, quantity=2, discount=0, unit_price=10000)],
        payments=[dict(method="Cash", amount=22800 + FEE)],
    )
    edit["fulfillment"]["shipping_cost"] = 99999  # fulfillment is locked: ignored on edit
    quote = client.post("/api/pos/quote", json=edit).json
    assert (quote["shipping"], quote["total"]) == (FEE, 27800)
    r = client.post("/api/pos/sales", json=edit)
    assert r.status_code == 200, r.json
    again = dict(edit, revision=2)
    assert client.post("/api/pos/sales", json=again).status_code == 200
    with app.app_context():
        sale = db.session.get(Sale, sid)
        assert (sale.revision, sale.total, sale.shipping_charge) == (3, 27800, FEE)
        assert sum(p.amount for p in sale.payments) == 27800
        assert ShippingOrder.query.count() == 1 and ShippingOrder.query.one().shipping_cost == FEE
        assert db.session.get(Product, 1).stock == 8
    # The POS editor is told the fee it must keep.
    assert '"shipping": 5000' in client.get(f"/sales/{sid}/edit").text.replace("&#34;", '"')


# 7 -------------------------------------------------------------------------------
def test_invoice_receipt_details_history_and_reports_agree(app, client):
    sid = client.post("/api/pos/sales", json=pos()).json["id"]
    detail = client.get(f"/api/sales/{sid}").json
    assert (detail["shipping"], detail["total"]) == (FEE, 16400)
    for url in (f"/sales/{sid}/invoice", f"/sales/{sid}/invoice?receipt=1"):
        html = client.get(url).text
        assert "Shipping fee" in html and money(FEE) in html and money(16400) in html
    assert money(16400) in client.get("/sales").text
    with app.app_context():
        oid = ShippingOrder.query.one().id
    ship = client.get(f"/api/shipping/{oid}").json
    assert ship["sale_totals"]["shipping"] == FEE and ship["sale_totals"]["total"] == 16400
    assert ship["order"]["shipping_billed"] is True
    report = client.get("/reports?kind=sales").text
    assert ">Shipping<" in report and money(FEE) in report and money(16400) in report
    profit = client.get("/reports?kind=profit").text
    assert "Shipping fees billed" in profit
    # Product profit is unaffected by the fee: 100.00 price − 50.00 cost = 50.00.
    from services.analytics import sale_stats

    with app.app_context():
        assert sale_stats(Sale.query.all())["profit"] == 5000


# 8 -------------------------------------------------------------------------------
def test_client_cannot_dictate_totals(app, client):
    tampered = pos(payments=[dict(method="Cash", amount=11400)], total=11400, shipping=0, grand_total=11400)
    assert client.post("/api/pos/sales", json=tampered).status_code == 400
    bad_fee = pos()
    bad_fee["fulfillment"]["shipping_cost"] = "50"
    assert client.post("/api/pos/sales", json=bad_fee).status_code == 400
    neg = pos()
    neg["fulfillment"]["shipping_cost"] = -1
    assert client.post("/api/pos/sales", json=neg).status_code == 400
    with app.app_context():
        assert Sale.query.count() == 0


def test_duplicate_checkout_charges_once(app, client):
    first = client.post("/api/pos/sales", json=pos())
    second = client.post("/api/pos/sales", json=pos())  # same token: a retried submit
    assert first.status_code == second.status_code == 200
    assert first.json["id"] == second.json["id"]
    with app.app_context():
        assert Sale.query.count() == 1 and ShippingOrder.query.count() == 1
        assert db.session.get(Product, 1).stock == 9


# 9 -------------------------------------------------------------------------------
def test_partial_refund_keeps_fee_and_reduces_last_payment_first(app, client):
    data = pos(
        items=[dict(product_id=1, quantity=2, discount=0, unit_price=10000)],
        payments=[dict(method="Cash", amount=20000), dict(method="Visa", amount=7800)],
    )
    sid = client.post("/api/pos/sales", json=data).json["id"]
    with app.app_context():
        item_id = db.session.get(Sale, sid).items[0].id
    r = client.post(f"/sales/{sid}/refund", json={"items": [{"item_id": item_id, "quantity": 1}]})
    assert r.status_code in (200, 302)
    with app.app_context():
        sale = db.session.get(Sale, sid)
        assert sale.status == "Completed"
        assert (sale.total, sale.shipping_charge) == (11400 + FEE, FEE)
        # 114.00 refunded: Visa (last entered) 78.00 first, then 36.00 from Cash.
        assert [(p.method, p.amount) for p in sale.payments] == [("Cash", 16400)]
        assert sale.payment == "Cash"
        assert sum(p.amount for p in sale.payments) == sale.total
        assert db.session.get(Product, 1).stock == 9
        assert InventoryMovement.query.filter_by(kind="Partial Refund").one().quantity == 1
        assert "refunded Visa 78.00, Cash 36.00" in sale.note


def test_full_refund_and_void_reverse_the_whole_invoice(app, client):
    sid = client.post("/api/pos/sales", json=pos()).json["id"]
    assert client.post(f"/sales/{sid}/refund").status_code == 302
    sid2 = client.post("/api/pos/sales", json=pos(token="e" * 48)).json["id"]
    assert client.post(f"/sales/{sid2}/delete", json={"cancel_reason": "Customer cancelled"}).status_code == 302
    with app.app_context():
        assert db.session.get(Sale, sid).status == "Refunded"
        assert db.session.get(Sale, sid2).status == "Voided"
        assert db.session.get(Product, 1).stock == 10
    profit = client.get("/reports?kind=profit").text
    row = re.search(r"Shipping fees billed</td><td[^>]*>([^<]+)<", profit)
    assert row and "0.00" in row.group(1)


def test_backups_restore_after_partial_refund(app, client):
    data = pos(items=[dict(product_id=1, quantity=2, discount=0, unit_price=10000)],
               payments=[dict(method="Cash", amount=27800)])
    sid = client.post("/api/pos/sales", json=data).json["id"]
    with app.app_context():
        item_id = db.session.get(Sale, sid).items[0].id
    client.post(f"/sales/{sid}/refund", json={"items": [{"item_id": item_id, "quantity": 1}]})
    backup = backup_response(app, client)
    assert backup.status_code == 200
    r = client.post("/settings/restore", data={"password": "test-password-123", "confirm": "RESTORE",
                    "backup": (io.BytesIO(backup.data), "b.zip")}, content_type="multipart/form-data")
    assert r.status_code == 202
    assert finish_restore(app)["restored"] is True


def test_restore_accepts_legacy_partial_refunds_but_not_corruption(app, client):
    """Partial refunds made before this fix left the original payment recorded."""
    sid = client.post("/api/pos/sales", json=pos(fulfillment={"method": "pickup"},
                      payments=[dict(method="Cash", amount=11400)])).json["id"]
    with app.app_context():
        sale = db.session.get(Sale, sid)
        sale.payments[0].amount = 22800  # legacy: payment kept at the pre-refund amount
        sale.note = "[Partial refund: 1x Test Product]"
        db.session.commit()
    ok = backup_response(app, client)
    client.post("/settings/restore", data={"password": "test-password-123", "confirm": "RESTORE",
                "backup": (io.BytesIO(ok.data), "b.zip")}, content_type="multipart/form-data")
    assert finish_restore(app)["restored"] is True
    client2 = app.test_client()
    assert client2.post("/login", data={"username": "admin", "password": "test-password-123"}).status_code == 302
    with app.app_context():
        sale = db.session.get(Sale, sid)
        sale.note = ""  # same mismatch without the partial-refund footprint = corruption
        db.session.commit()
    bad = backup_response(app, client2)
    client2.post("/settings/restore", data={"password": "test-password-123", "confirm": "RESTORE",
                 "backup": (io.BytesIO(bad.data), "b.zip")}, content_type="multipart/form-data")
    snap = finish_restore(app)
    assert snap["restored"] is False and "inconsistent invoice" in snap["message"]


# 10 ------------------------------------------------------------------------------
def test_billed_fee_cannot_be_changed_from_the_shipment(app, client):
    client.post("/api/pos/sales", json=pos())
    with app.app_context():
        oid = ShippingOrder.query.one().id
    r = client.post(f"/api/shipping/{oid}", json={"shipping_cost": 6000})
    assert r.status_code == 400 and "billed on invoice" in r.json["error"]
    same = client.post(f"/api/shipping/{oid}", json={"shipping_cost": FEE, "courier": "Aramex"})
    assert same.status_code == 200
    with app.app_context():
        assert ShippingOrder.query.one().shipping_cost == FEE
        assert Sale.query.one().total == 16400


def test_classic_sales_form_and_payment_rows_untouched_without_shipping(app, client):
    from test_app import sale_data

    assert client.post("/sales/new", data=sale_data()).status_code == 302
    with app.app_context():
        sale = Sale.query.one()
        assert sale.shipping_charge == 0
        assert sale.total == sale.subtotal - sale.discount + sale.tax
        assert SalePayment.query.count() == 0
