"""Regression tests for the UI functionality, navigation and popup overhaul."""

import re
import threading
import time
from pathlib import Path

import services.core as core
from test_app import app, client, sale_data  # noqa: F401
from models import Category, Customer, Product, Purchase, Sale, Supplier, db

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"


def login(app, username="admin"):
    c = app.test_client()
    assert c.post("/login", data={"username": username, "password": "test-password-123"}).status_code == 302
    return c


def test_concurrent_refunds_restore_stock_once(app, client, monkeypatch):
    """Two simultaneous refunds of one invoice must not put the stock back twice."""
    assert client.post("/sales/new", data=sale_data()).status_code == 302
    with app.app_context():
        assert db.session.get(Product, 1).stock == 8
    original = core.move

    def slow_move(*args, **kwargs):
        time.sleep(0.3)  # widen the window between the status check and the write
        return original(*args, **kwargs)

    monkeypatch.setattr(core, "move", slow_move)
    clients = [login(app), login(app)]
    codes = []

    def refund(c):
        codes.append(c.post("/sales/1/refund").status_code)

    threads = [threading.Thread(target=refund, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert sorted(codes) == [302, 400]
    with app.app_context():
        assert db.session.get(Product, 1).stock == 10
        assert db.session.get(Sale, 1).status == "Refunded"


def test_void_requires_reason_before_touching_stock(app, client):
    client.post("/sales/new", data=sale_data())
    assert client.post("/sales/1/delete", json={}).status_code == 400
    with app.app_context():
        assert db.session.get(Product, 1).stock == 8
        assert db.session.get(Sale, 1).status == "Completed"


def test_contact_edit_link_opens_full_edit_mode_and_keeps_search(app, client):
    with app.app_context():
        db.session.add(Customer(name="Zed Customer"))
        db.session.commit()
        cid = Customer.query.filter_by(name="Zed Customer").one().id
    html = client.get("/customers?q=Zed").text
    # Edit must not be swapped as a table-only partial (that kept the Add form).
    assert re.search(rf'href="/customers\?q=Zed&amp;edit={cid}" data-no-partial', html)
    edit = client.get(f"/customers?q=Zed&edit={cid}").text
    assert f'<input name="id" type="hidden" value="{cid}">' in edit
    assert 'href="/customers?q=Zed">' in edit  # Cancel keeps the search
    assert 'data-reload-url="/customers?q=Zed"' in edit


def test_contact_save_and_remove_report_results(app, client):
    r = client.post("/contacts/customers/save", data={"name": "New One"}, follow_redirects=True)
    assert "Saved." in r.text
    with app.app_context():
        cid = Customer.query.filter_by(name="New One").one().id
    r = client.post(f"/contacts/customers/{cid}/delete", follow_redirects=True)
    assert "Record removed." in r.text
    # A removed record can no longer be opened for editing.
    assert '<input name="id" type="hidden"' not in client.get(f"/customers?edit={cid}").text


def test_destructive_forms_name_the_record(app, client):
    html = client.get("/products").text
    assert 'data-confirm-detail="Test Product · TEST-001"' in html
    assert 'data-confirm-title="Delete product?"' in html
    html = client.get("/customers").text
    assert 'data-confirm-detail="Customer"' in html


def create_po(client, token):
    from werkzeug.datastructures import MultiDict

    data = MultiDict([("supplier_id", "1"), ("product_id", "1"), ("quantity", "1"), ("unit_cost", "50"), ("token", token)])
    assert client.post("/purchases/new", data=data).status_code == 302
    return Purchase.query.filter_by(token=token).one()


def test_purchase_actions_confirm_with_invoice_and_translation(app, client):
    with app.app_context():
        order = create_po(client, "po1")
        pid, invoice = order.id, order.invoice
    html = client.get(f"/purchases?selected={pid}").text
    assert 'data-confirm="Cancel this purchase order?"' in html
    assert f'data-confirm-detail="{invoice}"' in html
    assert 'data-confirm-tone="danger"' in html and 'data-confirm-tone="primary"' in html


def test_report_category_filter_survives_rename_and_filters_purchases(app, client):
    client.post("/sales/new", data=sale_data())
    with app.app_context():
        db.session.add(Category(name="Other"))
        db.session.commit()
    rows = client.get("/reports?kind=sales&category_id=1").text
    assert "INV-" in rows
    with app.app_context():
        db.session.get(Category, 1).name = "Renamed Electronics"
        db.session.commit()
    assert "INV-" in client.get("/reports?kind=sales&category_id=1").text
    assert "INV-" not in client.get("/reports?kind=sales&category_id=2").text


def test_report_view_all_keeps_date_range(client):
    html = client.get("/reports?from=2026-01-01&to=2026-01-31").text
    assert "kind=products" in html
    assert re.search(r'href="/reports\?from=2026-01-01&amp;to=2026-01-31&amp;kind=products"', html)


def test_dashboard_links_open_matching_data(app, client):
    html = client.get("/").text
    today = re.search(r'href="/sales\?from=(\d{4}-\d{2}-\d{2})&amp;to=\1"', html)
    assert today, "Sales Today must open today's sales"
    assert 'href="/purchases?status=open"' in html or "Pending Purchases" not in html
    assert "/settings#backup" not in html


def test_open_purchases_filter_lists_pending_and_processing_beyond_30_days(app, client):
    from datetime import timedelta
    from models import now

    with app.app_context():
        old = create_po(client, "po-old")
        old.created_at = now() - timedelta(days=90)
        old.status = "Processing"
        db.session.commit()
        invoice = old.invoice
    assert invoice in client.get("/purchases?status=open").text
    assert invoice not in client.get("/purchases?status=Processing").text  # default 30-day window


def test_maintenance_and_audit_forms_with_action_fields_are_safe(client):
    """Fields named "action" shadow form.action; scripts must read the attribute."""
    for name in ("router.js", "partial.js", "backups.js", "product-media.js"):
        src = (JS / name).read_text(encoding="utf-8")
        assert not re.search(r"\bform\.(action|method)\b", src), name


def test_no_native_browser_dialogs_in_scripts():
    pattern = re.compile(r"(?<![\w.])(?:window\.)?(confirm|alert)\(")
    offenders = []
    for path in JS.glob("*.js"):
        for line in path.read_text(encoding="utf-8").splitlines():
            # Fallbacks used only when the shared dialog layer is missing are allowed.
            if pattern.search(line) and "StoreProUI" not in line and "ui ?" not in line and "ui()" not in line:
                if "window.confirm(opts" in line or "window.confirm(o.message" in line or "window.confirm(verdict" in line or "window.confirm(confirmText" in line:
                    continue
                if path.name == "ui.js":
                    continue
                offenders.append(f"{path.name}: {line.strip()[:80]}")
    assert not offenders, offenders


def test_shared_dialog_is_on_every_page_and_translated(app, client):
    html = client.get("/").text
    assert 'id="sp-confirm-modal"' in html and 'id="sp-ui-strings"' in html
    assert html.index("js/ui.js") < html.index("js/partial.js") < html.index("js/router.js")
    with app.app_context():
        from services.core import save_setting

        save_setting("language", "ar")
        db.session.commit()
    html = client.get("/").text
    assert "يرجى التأكيد" in html  # Please confirm
    assert "&#34;Delete shipment?&#34;: &#34;" in html  # script strings shipped in Arabic


def test_script_strings_are_registered_and_translated():
    from services.i18n import AR, JS_STRINGS

    pattern = re.compile(r"""\b(?:tr|tx|ui\.t|ui\(\)\.t)\(\s*(["'])((?:(?!\1).)+?)\1""")
    keys = set()
    for path in JS.glob("*.js"):
        keys.update(m.group(2) for m in pattern.finditer(path.read_text(encoding="utf-8")))
    missing = sorted(k for k in keys if k not in JS_STRINGS or k not in AR)
    assert not missing, missing[:20]


def test_pos_cannot_overwrite_customer_profile_without_customers_edit(app, client):
    from models import Permission, UserPermissionDenial
    from test_orders import delivery_invoice

    with app.app_context():
        perm = Permission.query.filter_by(key="customers.edit").one()
        db.session.add(UserPermissionDenial(user_id=1, permission_id=perm.id))
        db.session.commit()
        before = db.session.get(Customer, 1).phone
    payload = delivery_invoice()
    payload["fulfillment"]["update_profile"] = True
    assert client.post("/api/pos/sales", json=payload).status_code == 403
    with app.app_context():
        assert db.session.get(Customer, 1).phone == before
        assert Sale.query.count() == 0
    payload["fulfillment"]["update_profile"] = False
    assert client.post("/api/pos/sales", json=payload).status_code == 200


def test_product_edit_cannot_change_stock_without_adjustment_permission(app, client):
    from models import Permission, UserPermissionDenial

    with app.app_context():
        perm = Permission.query.filter_by(key="inventory.stock_adjustment").one()
        db.session.add(UserPermissionDenial(user_id=1, permission_id=perm.id))
        db.session.commit()
    form = client.get("/products/1/edit").text
    assert 'name="current_stock"' in form and "aria-readonly" in form
    data = {
        "name": "Test Product", "sku": "TEST-001", "barcode": "12345678", "category_id": "1",
        "supplier_id": "1", "cost": "50", "price": "100", "minimum": "5",
        "current_stock": "25", "stock_baseline": "10",
    }
    assert client.post("/products/1/edit", data=data).status_code == 403
    with app.app_context():
        assert db.session.get(Product, 1).stock == 10


def test_templates_have_no_inline_scripts_or_handlers():
    """The CSP (script-src 'self') silently blocks inline code, so none may ship."""
    offenders = []
    for path in (ROOT / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        # JSON data blocks (type="application/json") are never executed and are fine.
        if re.search(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>", text) or re.search(
            r"\son(click|load|change|submit|error|input)=", text
        ):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, offenders


def test_csp_allows_local_image_previews_only(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "img-src 'self' data: blob:;" in csp and "script-src 'self';" in csp


def test_maintenance_reports_failure_honestly(app, client, monkeypatch):
    import services.maintenance as maintenance

    monkeypatch.setattr(maintenance, "checkpoint_wal", lambda *a, **k: (False, "busy=1, log=10, checkpointed=5"))
    r = client.post("/settings/maintenance/run", data={"action": "checkpoint"}, follow_redirects=True)
    assert "did not complete" in r.text and "completed." not in r.text.split("did not complete")[0][-200:]


def test_verify_all_backups_checks_configured_folders(app, tmp_path):
    from services.core import save_setting
    from services.maintenance import verify_all_backup_archives

    custom = tmp_path / "custom-primary"
    custom.mkdir()
    (custom / "storepro-20260101-000000-abcdef.zip").write_bytes(b"not a zip")
    with app.app_context():
        save_setting("backup_primary", str(custom))
        db.session.commit()
    result = verify_all_backup_archives(app)
    assert result["total"] >= 1 and any("storepro-20260101" in f for f in result["failures"])


def test_settings_save_rejects_missing_backup_folder(app, client, tmp_path):
    from services.core import DEFAULTS

    missing = tmp_path / "does-not-exist"
    r = client.post("/settings", data=DEFAULTS | {"backup_primary": str(missing)})
    assert r.status_code == 400
    assert not missing.exists()  # nothing is created behind the user's back
    with app.app_context():
        from services.core import settings

        assert settings().get("backup_primary", "") != str(missing)


def test_editing_own_account_keeps_session(app, client):
    with app.app_context():
        from models import User

        me = db.session.get(User, 1)
        data = {"id": "1", "name": "Admin Renamed", "username": me.username, "role_id": str(me.role_id), "active": "1"}
    assert client.post("/settings/users", data=data).status_code == 302
    assert client.get("/").status_code == 200  # still signed in
    assert "Admin Renamed" in client.get("/").text


def test_orders_all_counter_matches_all_list(app, client):
    from test_orders import delivery_invoice

    assert client.post("/api/pos/sales", json=delivery_invoice()).status_code == 200
    html = client.get("/orders?tab=shipping").text
    m = re.search(r'href="/orders\?tab=all"[^>]*>[^<]*<span class="count-pill">(\d+)</span>', html)
    assert m and m.group(1) == "1"
    assert 'href="/orders?tab=all" class="active"' not in html  # default view is open shipments, not "All"


def test_stock_adjustment_follows_server_redirect(client):
    html = client.get("/inventory/adjust").text
    assert "data-follow-redirect" in html and 'data-confirm-detail-from="#product-search, #adjust-type, #adjust-qty"' in html
