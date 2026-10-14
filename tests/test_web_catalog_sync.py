"""StorePro -> Next Chip catalog publisher (Stage 1: catalog only).

Runs against an isolated test database and a local fake website that checks
HMAC signatures independently. Nothing here touches instance/store.db or the
network beyond 127.0.0.1.
"""

import hashlib
import hmac
import io
import json
import logging
import sqlite3
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from test_app import app, client  # noqa: F401
from models import Category, Product, ProductImage, WebListing, db
from services import web_catalog_sync as sync

SECRET = "s" * 48


def png_bytes(color=(10, 200, 30), size=(40, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class FakeWebsite:
    """Minimal Next Chip endpoint: verifies signatures, stores media, answers like the real API."""

    def __init__(self, secret=SECRET):
        self.secret = secret
        self.requests = []
        self.media = {}
        self.snapshots = []
        self.script = []  # optional queued (status, body) answers for the snapshot endpoint
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                if status in (301, 302):
                    self.send_header("Location", "https://evil.example/collect")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                ts = self.headers.get("X-NextChip-Timestamp", "")
                nonce = self.headers.get("X-NextChip-Nonce", "")
                canonical = "\n".join(["NEXTCHIP-SYNC-V1", self.command, self.path, ts, nonce, hashlib.sha256(body).hexdigest()])
                expected = "v1=" + hmac.new(site.secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
                ok = hmac.compare_digest(expected, self.headers.get("X-NextChip-Signature", ""))
                site.requests.append({"method": self.command, "path": self.path, "signed": ok, "nonce": nonce, "body": body})
                if not ok:
                    return self._reply(401, {"error": "unauthorized"})
                if self.path == "/api/storepro/media/check":
                    hashes = json.loads(body)["hashes"]
                    return self._reply(200, {"missing": [h for h in hashes if h not in site.media]})
                if self.path.startswith("/api/storepro/media/"):
                    digest = self.path.rsplit("/", 1)[1]
                    assert hashlib.sha256(body).hexdigest() == digest
                    site.media[digest] = body
                    return self._reply(201, {"status": "stored"})
                if self.path == "/api/storepro/catalog-sync":
                    if site.script:
                        status, payload = site.script.pop(0)
                        return self._reply(status, payload)
                    snap = json.loads(body)
                    site.snapshots.append(snap)
                    return self._reply(
                        200,
                        {
                            "status": "applied",
                            "snapshotId": snap["snapshot"]["id"],
                            "publishedProducts": len(snap["products"]),
                            "unpublishedProducts": 0,
                            "missingMedia": [],
                        },
                    )
                if self.path == "/api/storepro/status":
                    return self._reply(200, {"publishedProducts": len(site.snapshots[-1]["products"]) if site.snapshots else 0, "stale": False})
                return self._reply(404, {"error": "not_found"})

            do_GET = do_POST = do_PUT = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def site():
    s = FakeWebsite()
    yield s
    s.close()


def cfg_for(url, **extra):
    env = {"NEXT_CHIP_SYNC_ENABLED": "true", "NEXT_CHIP_SYNC_URL": url, "NEXT_CHIP_SYNC_SECRET": SECRET}
    env.update(extra)
    return env


def seed(app):
    """Products covering every publication rule. Product 1 comes from the base fixture."""
    with app.app_context():
        root = app.config["ROOT"]
        db.session.add(Category(name="Gaming Mice", icon="mouse", description="Light mice"))
        db.session.flush()
        mice = Category.query.filter_by(name="Gaming Mice").one()
        rows = [
            # name, sku, brand, price, stock, minimum, active
            ("Vortek V1 Air", "VTK-V1A", "Vortek", 329900, 14, 3, True),
            ("Low Stock Pad", "PAD-LOW", "", 89900, 2, 5, True),
            ("Sold Out Mic", "MIC-OUT", "Sonaris", 199900, 0, 2, True),
            ("Archived Mouse", "OLD-001", "Vortek", 99900, 4, 1, False),
            ("Free Sticker", "STICK-0", "", 0, 50, 1, True),
            ("Not Listed", "NOPE-1", "Vortek", 50000, 5, 1, True),
        ]
        for name, sku, brand, price, stock, minimum, active in rows:
            db.session.add(Product(name=name, sku=sku, brand=brand, category_id=mice.id, cost=price // 2, price=price, stock=stock, minimum=minimum, active=active, location="Shelf B", barcode=None))
        db.session.flush()
        by_sku = {p.sku: p for p in Product.query.all()}
        # Gallery image for the Vortek; legacy single image for the base product; a missing file for the pad.
        vortek = by_sku["VTK-V1A"]
        folder = root / "static" / "uploads" / "products" / str(vortek.id)
        folder.mkdir(parents=True)
        (folder / "a.png").write_bytes(png_bytes())
        db.session.add(ProductImage(product_id=vortek.id, file_path=f"products/{vortek.id}/a.png", file_name="a.png", is_primary=True))
        (root / "static" / "uploads" / "legacy.png").write_bytes(png_bytes((200, 0, 0), (20, 20)))
        by_sku["TEST-001"].image = "legacy.png"
        db.session.add(ProductImage(product_id=by_sku["PAD-LOW"].id, file_path="products/x/missing.png", file_name="missing.png", is_primary=True))
        for sku in ("TEST-001", "VTK-V1A", "PAD-LOW", "MIC-OUT", "OLD-001", "STICK-0"):
            db.session.add(WebListing(product_id=by_sku[sku].id, published=True))
        db.session.add(WebListing(product_id=by_sku["NOPE-1"].id, published=False))
        listing = db.session.get(WebListing, vortek.id)
        listing.name_ar = "فورتك في 1 إير"
        listing.description_en = "A 49 g wireless mouse. Great for FPS."
        listing.max_per_order = 3
        db.session.commit()
        return {sku: p.id for sku, p in by_sku.items()}


# ---------------------------------------------------------------- mapping


def test_snapshot_maps_only_public_fields_and_respects_publication(app):
    ids = seed(app)
    with app.app_context():
        cfg = sync.load_config(app.config["ROOT"], environ={})
        snap, media, warnings = sync.build_snapshot(cfg, app.config["ROOT"])
    products = {p["sku"]: p for p in snap["products"]}
    assert set(products) == {"TEST-001", "VTK-V1A", "PAD-LOW", "MIC-OUT"}
    assert any("OLD-001" in w and "archived" in w for w in warnings)
    assert any("STICK-0" in w and "no selling price" in w for w in warnings)
    assert any("PAD-LOW" in w and "missing" in w for w in warnings)
    v = products["VTK-V1A"]
    assert v["id"] == f"sp-{ids['VTK-V1A']}"
    assert v["slug"] == f"vortek-v1-air-{ids['VTK-V1A']}"
    assert v["name"] == {"en": "Vortek V1 Air", "ar": "فورتك في 1 إير"}
    assert v["description"]["en"] == "A 49 g wireless mouse. Great for FPS."
    assert (v["price"], v["maxPerOrder"]) == (329900, 3)
    assert (v["availability"], v["orderableQuantity"]) == ("in_stock", 3)  # 14 in stock, capped at 3
    assert v["brandId"] == "spb-vortek" and v["categoryId"].startswith("spc-")
    assert len(v["images"]) == 1 and v["images"][0]["contentType"] == "image/png"
    assert (v["images"][0]["width"], v["images"][0]["height"]) == (40, 30)
    assert products["PAD-LOW"]["availability"] == "low_stock" and products["PAD-LOW"]["brandId"] is None
    assert products["PAD-LOW"]["images"] == []
    assert (products["MIC-OUT"]["availability"], products["MIC-OUT"]["orderableQuantity"]) == ("out_of_stock", 0)
    assert products["TEST-001"]["images"][0]["width"] == 20  # legacy image
    assert products["TEST-001"]["name"]["ar"] == "Test Product"  # falls back to the StorePro name
    # Private data never leaves StorePro.
    text = json.dumps(snap)
    for private in ("cost", "supplier", "barcode", "location", "minimum", "Shelf B", "12345678"):
        assert private not in text
    assert all(p["orderableQuantity"] <= p["maxPerOrder"] for p in snap["products"])
    assert snap["currency"] == "EGP" and snap["snapshot"]["complete"] is True
    assert {c["id"] for c in snap["categories"]} == {p["categoryId"] for p in snap["products"]}
    assert len(media) == 2


def test_snapshot_ids_and_content_are_deterministic(app):
    seed(app)
    with app.app_context():
        cfg = sync.load_config(app.config["ROOT"], environ={})
        a, _, _ = sync.build_snapshot(cfg, app.config["ROOT"])
        b, _, _ = sync.build_snapshot(cfg, app.config["ROOT"])
    assert a["products"] == b["products"] and a["categories"] == b["categories"]
    assert a["snapshot"]["id"].split("-")[-1] == b["snapshot"]["id"].split("-")[-1]  # same content hash suffix


# ---------------------------------------------------------------- configuration


def test_configuration_rules_and_secret_never_exposed(tmp_path):
    (tmp_path / "instance").mkdir()
    (tmp_path / "instance" / "web-sync.env").write_text(
        f"NEXT_CHIP_SYNC_ENABLED=true\nNEXT_CHIP_SYNC_URL=https://shop.example.com/\nNEXT_CHIP_SYNC_SECRET={SECRET}\n", encoding="utf-8"
    )
    cfg = sync.load_config(tmp_path, environ={})
    assert (cfg.enabled, cfg.url, cfg.configured) == (True, "https://shop.example.com", True)
    assert SECRET not in json.dumps(cfg.public()) and SECRET not in repr(cfg)
    assert sync.load_config(tmp_path, environ={"NEXT_CHIP_SYNC_ENABLED": "false"}).enabled is False  # env wins
    assert not sync.load_config(tmp_path, environ={}).problems
    plain = sync.load_config(tmp_path, environ={"NEXT_CHIP_SYNC_URL": "http://shop.example.com"})
    assert plain.problems and not plain.configured
    assert sync.load_config(tmp_path, environ={"NEXT_CHIP_SYNC_URL": "http://localhost:3100"}).url == "http://localhost:3100"
    assert sync.load_config(tmp_path, environ={"NEXT_CHIP_SYNC_URL": "https://shop.example.com/api?x=1"}).problems
    assert sync.load_config(tmp_path, environ={"NEXT_CHIP_SYNC_SECRET": "short"}).problems
    assert sync.load_config(tmp_path / "missing", environ={}).enabled is False  # disabled by default


# ---------------------------------------------------------------- publishing


def test_disabled_and_dry_run_send_nothing(app, site):
    seed(app)
    with app.app_context():
        root = app.config["ROOT"]
        off = sync.load_config(root, environ={"NEXT_CHIP_SYNC_URL": site.url, "NEXT_CHIP_SYNC_SECRET": SECRET})
        assert sync.run_sync("manual", root=root, cfg=off)["skipped"] is True
        dry = sync.run_sync("cli", dry_run=True, root=root, cfg=sync.load_config(root, environ=cfg_for(site.url)))
        assert dry["ok"] and dry["products"] == 4 and dry["images"] == 2
    assert site.requests == []


def test_full_sync_uploads_missing_media_signs_requests_and_records_state(app, site, caplog):
    seed(app)
    caplog.set_level(logging.DEBUG)
    with app.app_context():
        root = app.config["ROOT"]
        cfg = sync.load_config(root, environ=cfg_for(site.url))
        result = sync.run_sync("manual", root=root, cfg=cfg)
        assert result["ok"], result
        state = sync.load_state(root)
        assert state["last_ok"] is True and state["last_product_count"] == 4 and state["last_complete"] is True
        assert state["last_snapshot_id"] == site.snapshots[-1]["snapshot"]["id"]
        assert all(r["signed"] for r in site.requests)
        assert len({r["nonce"] for r in site.requests}) == len(site.requests)
        assert [r["path"] for r in site.requests if r["method"] == "PUT"].__len__() == 2
        # Second run: media already present, nothing re-uploaded, product count stable (idempotent).
        site.requests.clear()
        assert sync.run_sync("manual", root=root, cfg=cfg)["ok"]
        assert not [r for r in site.requests if r["method"] == "PUT"]
        assert len(site.snapshots[-1]["products"]) == 4
        remote, error = sync.website_status(cfg)
        assert error is None and remote["publishedProducts"] == 4
    state_text = (root / "instance" / "web_sync_state.json").read_text(encoding="utf-8")
    assert SECRET not in state_text and SECRET not in caplog.text


def test_price_change_and_unpublish_flow_through(app, site):
    ids = seed(app)
    with app.app_context():
        root = app.config["ROOT"]
        cfg = sync.load_config(root, environ=cfg_for(site.url))
        assert sync.run_sync("manual", root=root, cfg=cfg)["ok"]
        product = db.session.get(Product, ids["VTK-V1A"])
        product.price = 299900
        db.session.get(WebListing, ids["MIC-OUT"]).published = False
        db.session.commit()
        assert sync.run_sync("manual", root=root, cfg=cfg)["ok"]
    last = {p["sku"]: p for p in site.snapshots[-1]["products"]}
    assert last["VTK-V1A"]["price"] == 299900
    assert "MIC-OUT" not in last and site.snapshots[-1]["snapshot"]["complete"] is True
    assert site.snapshots[-1]["snapshot"]["sequence"] > site.snapshots[0]["snapshot"]["sequence"]


def test_retries_transient_errors_with_backoff(app, site):
    seed(app)
    site.script = [(503, {"error": "busy"}), (502, {})]
    sleeps = []
    with app.app_context():
        root = app.config["ROOT"]
        result = sync.run_sync("manual", root=root, cfg=sync.load_config(root, environ=cfg_for(site.url)), sleep=sleeps.append)
    assert result["ok"]
    assert sleeps == [2.0, 4.0]
    posts = [r for r in site.requests if r["path"] == "/api/storepro/catalog-sync"]
    assert len(posts) == 3 and len({r["nonce"] for r in posts}) == 3


def test_exhausted_retries_report_the_website_answer(app, site):
    seed(app)
    site.script = [(503, {"error": "sync_not_configured"})] * 3
    with app.app_context():
        root = app.config["ROOT"]
        result = sync.run_sync("manual", root=root, cfg=sync.load_config(root, environ=cfg_for(site.url)), sleep=lambda s: None)
    assert not result["ok"]
    assert "3 attempts" in result["error"] and "HTTP 503, sync_not_configured" in result["error"]
    assert "unreachable" not in result["error"]


def test_unreachable_website_is_reported_and_keeps_last_success(app, site):
    seed(app)
    with app.app_context():
        root = app.config["ROOT"]
        assert sync.run_sync("manual", root=root, cfg=sync.load_config(root, environ=cfg_for(site.url)))["ok"]
        first_success = sync.load_state(root)["last_success_at"]
        site.close()
        down = sync.load_config(root, environ=cfg_for(site.url, NEXT_CHIP_SYNC_TIMEOUT_SECONDS="5"))
        result = sync.run_sync("scheduled", root=root, cfg=down, sleep=lambda s: None)
        state = sync.load_state(root)
    assert not result["ok"] and "unreachable" in result["error"]
    assert state["last_ok"] is False and state["last_success_at"] == first_success and state["last_failure_at"]


def test_rejections_and_redirects_are_failures(app, site):
    seed(app)
    with app.app_context():
        root = app.config["ROOT"]
        cfg = sync.load_config(root, environ=cfg_for(site.url))
        site.script = [(422, {"error": "invalid_snapshot", "issues": [{"path": "products[0 sku=X].price", "message": "must be an integer"}]})]
        rejected = sync.run_sync("manual", root=root, cfg=cfg)
        assert not rejected["ok"] and "HTTP 422" in rejected["error"] and "sku=X" in rejected["error"]
        site.script = [(302, {})]
        redirected = sync.run_sync("manual", root=root, cfg=cfg)
        assert not redirected["ok"] and "HTTP 302" in redirected["error"]
        wrong = sync.load_config(root, environ=cfg_for(site.url, NEXT_CHIP_SYNC_SECRET="w" * 48))
        unauthorized = sync.run_sync("manual", root=root, cfg=wrong)
        assert not unauthorized["ok"] and "HTTP 401" in unauthorized["error"]


def test_concurrent_runs_are_refused(app, site):
    seed(app)
    with app.app_context():
        root = app.config["ROOT"]
        assert sync._RUN_LOCK.acquire(blocking=False)
        try:
            assert "already running" in sync.run_sync("manual", root=root, cfg=sync.load_config(root, environ=cfg_for(site.url)))["error"]
        finally:
            sync._RUN_LOCK.release()


# ---------------------------------------------------------------- admin UI and permissions


def test_website_page_publication_and_listing_editing(app, client):
    ids = seed(app)
    page = client.get("/settings/website")
    assert page.status_code == 200
    assert "Vortek V1 Air" in page.text and "Sync now" in page.text and SECRET not in page.text
    r = client.post("/settings/website/publish", data={"product_ids": [ids["NOPE-1"], ids["VTK-V1A"]], "published": [ids["NOPE-1"]]})
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(WebListing, ids["NOPE-1"]).published is True
        assert db.session.get(WebListing, ids["VTK-V1A"]).published is False
        assert db.session.get(WebListing, ids["PAD-LOW"]).published is True  # not on the submitted list: unchanged
    form = client.get(f"/settings/website/products/{ids['VTK-V1A']}")
    assert form.status_code == 200
    r = client.post(f"/settings/website/products/{ids['VTK-V1A']}", data={"published": "1", "name_en": "Vortek V1 Air (Black)", "name_ar": "", "description_en": "", "description_ar": "", "max_per_order": "4"})
    assert r.status_code == 302
    with app.app_context():
        listing = db.session.get(WebListing, ids["VTK-V1A"])
        assert (listing.published, listing.name_en, listing.max_per_order) == (True, "Vortek V1 Air (Black)", 4)
    bad = client.post(f"/settings/website/products/{ids['VTK-V1A']}", data={"max_per_order": "500"})
    assert bad.status_code in (302, 400)
    with app.app_context():
        assert db.session.get(WebListing, ids["VTK-V1A"]).max_per_order == 4


def test_website_page_keeps_store_language_and_shows_local_times(app, client, site):
    from services.core import save_setting

    seed(app)
    with app.app_context():
        root = app.config["ROOT"]
        assert sync.run_sync("manual", root=root, cfg=sync.load_config(root, environ=cfg_for(site.url)))["ok"]
        stamp = sync.load_state(root)["last_success_at"]
        save_setting("language", "ar")
        db.session.commit()
    page = client.get("/settings/website")
    assert page.status_code == 200
    # The sync settings must not shadow the store `config` the layout reads (direction, store name).
    assert '<html lang="ar" dir="rtl"' in page.text
    assert f'<time datetime="{stamp}">' in page.text
    assert stamp not in page.text.replace(f'datetime="{stamp}"', "")


def test_sync_button_reports_disabled_state(app, client):
    seed(app)
    r = client.post("/settings/website/sync", follow_redirects=True)
    assert r.status_code == 200
    assert "disabled" in r.text


def test_website_pages_require_permissions(app, client):
    seed(app)
    from test_permissions import login

    cashier = login(app, "cashier")
    assert cashier.get("/settings/website").status_code == 403
    assert cashier.post("/settings/website/sync").status_code == 403
    assert cashier.post("/settings/website/publish", data={"product_ids": ["1"], "published": ["1"]}).status_code == 403


# ---------------------------------------------------------------- schema and backups


def test_older_database_gains_web_listings_without_touching_data(app, tmp_path):
    from services.migrations import SCHEMA_VERSION, upgrade_sqlite

    with app.app_context():
        source = db.engine.url.database
    copy = tmp_path / "old.db"
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(copy)) as dst:
        src.backup(dst)
    with closing(sqlite3.connect(copy)) as c:
        c.execute("DROP TABLE web_listings")
        c.execute("PRAGMA user_version = 5")
        c.commit()
        before = c.execute("SELECT id, name, price, stock FROM products ORDER BY id").fetchall()
    upgrade_sqlite(copy)
    with closing(sqlite3.connect(copy)) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert tables == set(db.metadata.tables)  # what backup restore validation requires
        assert c.execute("SELECT id, name, price, stock FROM products ORDER BY id").fetchall() == before
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        cols = {r[1] for r in c.execute("PRAGMA table_info(web_listings)")}
        assert cols == {col.name for col in WebListing.__table__.columns}


def test_archiving_or_deleting_a_product_keeps_working_with_a_listing(app, client):
    ids = seed(app)
    with app.app_context():
        p = db.session.get(Product, ids["MIC-OUT"])  # zero stock, so the archive action is allowed
    r = client.post(f"/products/{ids['MIC-OUT']}/delete")
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(Product, ids["MIC-OUT"]).active is False
        cfg = sync.load_config(app.config["ROOT"], environ={})
        snap, _, warnings = sync.build_snapshot(cfg, app.config["ROOT"])
    assert "MIC-OUT" not in {p["sku"] for p in snap["products"]}
    assert any("MIC-OUT" in w for w in warnings)
