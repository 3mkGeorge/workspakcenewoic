"""SPA router regression checks: shell stability and asset integrity.

The router swaps only main.content; these tests pin the server-side
contract it depends on: every view renders the full shell, every static
asset referenced exists on disk, and mutations return followable HTML.
"""

import re

from test_app import app, client  # noqa: F401


def _assets(html):
    hrefs = re.findall(r'(?:href|src)="(/static/[^"]+)"', html)
    return [h.split("?")[0] for h in hrefs]


def test_shell_present_on_all_modules(client):
    for url in [
        "/",
        "/sales",
        "/sales/new",
        "/shipping",
        "/products",
        "/inventory",
        "/inventory/adjust",
        "/purchases",
        "/customers",
        "/suppliers",
        "/reports",
        "/backups",
        "/settings",
        "/settings/users",
        "/search?q=x",
        "/notifications",
    ]:
        html = client.get(url).data.decode()
        assert 'id="sidebar"' in html, url
        assert 'class="topbar"' in html, url
        assert 'class="content"' in html, url
        assert 'id="app-toast"' in html, url
        assert "js/router.js" in html and "css/router.css" in html, url


def test_no_view_depends_on_missing_assets(client):
    from pathlib import Path as _Path

    static = _Path(__file__).resolve().parents[1] / "static"
    checked = set()
    for url in ["/", "/sales", "/sales/new", "/shipping", "/products", "/inventory",
                "/purchases", "/reports", "/settings/users", "/settings/permissions"]:
        html = client.get(url).data.decode()
        for ref in _assets(html):
            if ref in checked:
                continue
            checked.add(ref)
            assert (static / ref.removeprefix("/static/")).exists(), (url, ref)


def test_post_flows_return_swappable_html(client):
    response = client.post(
        "/inventory/adjust",
        data={"product_id": "1", "quantity": "1", "reason": "SPA check"},
    )
    assert response.status_code == 302
    page = client.get(response.location)
    assert page.status_code == 200
    assert 'id="sidebar"' in page.data.decode()


def test_partial_regions_present(client):
    regions = {
        "/products": ['data-partial="product-table"', 'data-partial-form="product-table"'],
        "/inventory": ['data-partial="product-table"', 'data-partial-form="product-table"'],
        "/sales": ['data-partial="sales-main"', 'data-partial-form="sales-main"'],
        "/purchases": ['data-partial="purchases-main"', 'data-partial-form="purchases-main"'],
        "/shipping": ['data-partial="shipping-table"', 'data-partial-form="shipping-table"'],
        "/customers": ['data-partial="contacts-table"', 'data-partial-form="contacts-table"'],
        "/suppliers": ['data-partial="contacts-table"', 'data-partial-form="contacts-table"'],
        "/reports": ['data-partial="report-table"', 'data-partial-form="report-table"'],
        "/": ['data-partial="dash-chart"'],
    }
    for url, tokens in regions.items():
        html = client.get(url).data.decode()
        for token in tokens:
            assert token in html, (url, token)


def test_partial_content_matches_region(client):
    html = client.get("/products?q=TEST-001").data.decode()
    assert 'data-partial="product-table"' in html and "TEST-001" in html
    html = client.get("/?days=30").data.decode()
    assert 'data-partial="dash-chart"' in html


def test_ajax_reload_forms_present(app, client):
    from werkzeug.datastructures import MultiDict

    html = client.get("/inventory/adjust").data.decode()
    assert 'id="adjust-form"' in html and "data-ajax-reload" in html
    client.post(
        "/purchases/new",
        data=MultiDict(
            [
                ("token", "ajax-reload-check"),
                ("supplier_id", "1"),
                ("product_id", "1"),
                ("quantity", "2"),
                ("unit_cost", "10"),
            ]
        ),
    )
    html = client.get("/purchases?selected=1").data.decode()
    assert "data-ajax-reload" in html
    assert client.get("/settings/users").status_code == 200


def test_product_details_drawer_contract(client):
    """Row-menu 'Product Details' chain: trigger markup, drawer shell, API."""
    for url in ("/products", "/inventory"):
        html = client.get(url).data.decode()
        for token in (
            'data-product-details="1"',
            'id="product-details-drawer"',
            'id="product-details-backdrop"',
            'id="product-details-body"',
            'id="product-details-close"',
            "js/product-details.js",
        ):
            assert token in html, (url, token)
    data = client.get("/api/products/1/preview").json
    for key in (
        "thumb_image",
        "name",
        "sku",
        "category",
        "cost",
        "price",
        "stock",
        "supplier",
        "created_at",
        "updated_at",
        "status",
    ):
        assert key in data, key
    assert data["name"] == "Test Product" and data["sku"] == "TEST-001"
    assert client.get("/api/products/9999/preview").status_code == 404


def test_sale_details_modal_contract(app, client):
    """Sales table opens Invoice Details modal via AJAX; no side panel."""
    from test_app import sale_data

    assert client.post("/sales/new", data=sale_data()).status_code == 302
    html = client.get("/sales").data.decode()
    for token in (
        'data-sale-modal="1"',
        'id="saleDetailsModal"',
        "sale-modal-inv",
        "sale-modal-rows",
        "sale-modal-grand",
        "sale-modal-print",
        "sale-modal-receipt",
        "sale-modal-edit",
        "sale-modal-refund",
        "sale-modal-delete",
        "js/sale-modal.js",
        "css/sale-modal.css",
        "Invoice Information",
        "Financial Summary",
        "sale-main-grid",
        "sale-summary-card",
    ):
        assert token in html, token
    for legacy in ("detail-panel", "split-view sales-view"):
        assert legacy not in html, legacy
    data = client.get("/api/sales/1").json
    for key in (
        "invoice", "date", "datetime", "customer", "status", "payment",
        "payments", "user", "items", "subtotal", "discount", "tax_rate",
        "tax", "total", "currency", "note", "pickup_notes",
    ):
        assert key in data, key
    (item,) = data["items"]
    for key in ("product_id", "image", "name", "quantity", "price", "discount", "total"):
        assert key in item, key
    assert item["total"] == item["quantity"] * item["price"] - item["discount"]
    assert data["invoice"] == "INV-1001"
    assert client.get("/api/sales/9999").status_code == 404
    client.post("/logout")
    assert client.get("/api/sales/1").status_code == 401


def test_invoice_info_label_value_pairing():
    """Invoice Information labels must be DOM-bound to their own values."""
    import re
    from pathlib import Path

    src = Path("static/js/sale-modal.js").read_text(encoding="utf-8")
    body = src.split("function renderInfo")[1]
    for label in (
        "Invoice Number", "Date", "Customer", "Payment Method", "User",
        "Status", "Breakdown",
    ):
        assert f'"{label}"' in body, label
    assert len(re.findall(r"pair\(info,", body)) == 2  # loop call + Status
    assert "info.append(dt, dd)" not in body
    assert body.count('className = "ipair"') == 2
    css = Path("static/css/sale-modal.css").read_text(encoding="utf-8")
    assert ".sale-info-grid .ipair" in css
    assert "overflow-wrap: anywhere" not in css


def test_shipping_json_extras(app, client):
    from test_app import sale_data

    assert client.post("/sales/new", data=sale_data()).status_code == 302
    with app.app_context():
        from models import Customer, Sale, ShippingOrder, db

        sale = Sale.query.first()
        order = ShippingOrder(
            order_number="SHP-X1",
            sale_id=sale.id,
            tracking_code="TRK-X1",
            customer_name=sale.customer_name,
            customer_id=sale.customer_id,
            user_id=sale.user_id,
        )
        db.session.add(order)
        db.session.commit()
        oid = order.id
    data = client.post(f"/api/shipping/{oid}/status", json={"status": "Packed"}).json
    assert data["transitions"] == ["Ready For Shipment", "Cancelled"]
    data = client.post(f"/api/shipping/{oid}/status", json={"status": "Ready For Shipment"}).json
    assert data["transitions"] == ["Shipped", "Cancelled"]
    assert data["event"]["action"] == "Ready For Shipment" and data["event"]["actor"]
    assert data["event"]["at"]
    data = client.post(
        f"/api/shipping/{oid}",
        json={"courier": "Bosta", "tracking_code": "TRK-X1", "shipping_cost": 1000},
    ).json
    assert data["order"]["shipping_cost"] == 1000
    assert data["transitions"] == ["Shipped", "Cancelled"]


def test_shipping_detail_shell(client, app):
    from test_app import sale_data

    assert client.post("/sales/new", data=sale_data()).status_code == 302
    from models import Sale, ShippingOrder, db

    with app.app_context():
        sale = Sale.query.first()
        order = ShippingOrder(
            order_number="SHP-TEST",
            sale_id=sale.id,
            tracking_code="TRK-TEST",
            customer_name=sale.customer_name,
            user_id=sale.user_id,
        )
        db.session.add(order)
        db.session.commit()
        oid = order.id
    html = client.get(f"/shipping/{oid}").data.decode()
    assert 'id="ship-detail"' in html and 'id="sidebar"' in html
