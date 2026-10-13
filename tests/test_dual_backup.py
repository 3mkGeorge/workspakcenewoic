"""Failure isolation, transaction hooks, recovery safety, and nonblocking delivery."""

import threading
import time
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from test_app import app, client, backup_response, finish_restore  # noqa: F401
from models import db, BackupLog, Product, Customer
from services.core import settings, save_setting
from services import dual_backup as service
from services.backups import restore_backup


def tick(app):
    with app.app_context():
        app.extensions["backups"].tick()


def test_identical_dual_archives_and_media(app, client):
    with app.app_context():
        name = "a" * 32 + ".png"
        Image.new("RGB", (8, 8), "red").save(
            app.config["ROOT"] / "static/uploads" / name
        )
        db.session.get(Product, 1).image = name
        db.session.commit()
    response = backup_response(app, client)
    state = client.get("/api/backups/status").json
    assert state["count"] == 2 and state["next_backup"]
    primary = app.config["ROOT"] / "backups" / state["files"][0]["name"]
    secondary = app.config["ROOT"] / "backups-secondary" / primary.name
    assert primary.read_bytes() == secondary.read_bytes() == response.data
    manifest = service.inspect_archive(primary)
    assert manifest["version"] == 2
    with zipfile.ZipFile(primary) as z:
        assert {"settings.json", "configuration.json", "uploads/" + name}.issubset(
            z.namelist()
        )
        assert not any("secret" in n for n in z.namelist())
    with app.app_context():
        assert BackupLog.query.count() == 2
        assert all(r.status == "Success" for r in BackupLog.query.all())
    assert client.get("/settings/backup-logs").status_code == 200
    assert b"Dual Backup" in client.get("/settings").data


def test_failed_secondary_preserves_primary_and_warns(app, client):
    root = app.config["ROOT"]
    bad = root / "unavailable"
    bad.write_text("not a directory")
    with app.app_context():
        save_setting("backup_secondary", str(bad))
        db.session.commit()
    assert client.post("/settings/backup").status_code == 202
    tick(app)
    state = client.get("/api/backups/status").json
    assert state["count"] == 1 and "1/2" in state["message"]
    assert any("Secondary" in s for s in state["warnings"])
    assert b"Backup health requires attention" in client.get("/").data
    with app.app_context():
        assert (
            BackupLog.query.filter_by(status="Failed", source="Secondary").count() == 1
        )
        assert (
            BackupLog.query.filter_by(status="Success", source="Primary").count() == 1
        )


def test_unlimited_retention_and_uncompressed_archives(app, client):
    root = app.config["ROOT"]
    sentinel = root / "backups/unrelated.zip"
    sentinel.write_text("Do not delete")
    with app.app_context():
        save_setting("backup_compression", "0")
        save_setting("backup_verification", "0")
        db.session.commit()
        for _ in range(4):
            results = service.run_backup()
            assert all(r["status"] == "Success" for r in results)
    assert len(list((root / "backups").glob("storepro-*.zip"))) == 4
    assert len(list((root / "backups-secondary").glob("storepro-*.zip"))) == 4
    assert sentinel.read_text() == "Do not delete"
    with zipfile.ZipFile(results[0]["path"]) as z:
        assert all(m.compress_type == zipfile.ZIP_STORED for m in z.infolist())


def test_live_commit_only_and_no_log_recursion(app, client):
    manager = app.extensions["backups"]
    manager.pending = False
    with app.app_context():
        db.session.add(Customer(name="Rolled back"))
        db.session.flush()
        db.session.rollback()
        assert not manager.pending
        db.session.add(Customer(name="Committed"))
        db.session.commit()
        assert manager.pending
    tick(app)
    assert not manager.pending
    with app.app_context():
        assert BackupLog.query.count() == 2
        assert all(r.reason == "Live" for r in BackupLog.query.all())
    tick(app)
    with app.app_context():
        assert BackupLog.query.count() == 2


@pytest.mark.parametrize("frequency", list(service.FREQUENCIES))
def test_schedule_due_and_disable(app, client, frequency):
    manager = app.extensions["backups"]
    with app.app_context():
        save_setting("backup_frequency", frequency)
        save_setting("backup_live", "0")
        db.session.commit()
    tick(app)
    assert abs(manager.next_due - time.time() - service.FREQUENCIES[frequency]) < 10
    manager.next_due = time.time() - 1
    tick(app)
    with app.app_context():
        assert BackupLog.query.filter_by(reason="Scheduled").count() == 2
        save_setting("auto_backup", "0")
        db.session.commit()
    tick(app)
    assert manager.snapshot()["next_backup"] is None


def test_backup_io_does_not_block_sales_requests(app, client, monkeypatch):
    original = service.replicate
    entered, release = threading.Event(), threading.Event()

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "replicate", slow)
    assert client.post("/settings/backup").status_code == 202
    worker = threading.Thread(target=tick, args=(app,))
    worker.start()
    assert entered.wait(5)
    try:
        start = time.monotonic()
        assert client.get("/api/pos/products?q=Test").status_code == 200
        assert time.monotonic() - start < 2
        with app.app_context():
            db.session.add(Customer(name="During backup"))
            db.session.commit()
        assert app.extensions["backups"].pending
        assert client.post("/settings/backup").status_code == 409
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive() and app.extensions["backups"].pending


@pytest.mark.parametrize("source", ["Primary", "Secondary"])
def test_restore_from_either_destination(app, client, source):
    backup_response(app, client)
    state = client.get("/api/backups/status").json
    chosen = next(f for f in state["files"] if f["source"] == source)
    with app.app_context():
        db.session.get(Product, 1).stock = 4
        db.session.commit()
    response = client.post(
        "/settings/restore",
        data={
            "source": source,
            "name": chosen["name"],
            "password": "test-password-123",
            "confirm": "RESTORE",
        },
    )
    assert response.status_code == 202
    assert finish_restore(app)["restored"]
    with app.app_context():
        assert db.session.get(Product, 1).stock == 10
    assert list((app.config["ROOT"] / "instance").glob("pre-restore-*.sqlite3"))
    assert client.get("/api/backups/status").status_code == 401


def test_tampering_rejected_without_changing_database(app, client):
    backup_response(app, client)
    path = next((app.config["ROOT"] / "backups").glob("*.zip"))
    with zipfile.ZipFile(path) as z:
        contents = {n: z.read(n) for n in z.namelist()}
    contents["settings.json"] = b"{}"
    corrupt = app.config["ROOT"] / "tampered.zip"
    with zipfile.ZipFile(corrupt, "w") as z:
        for name, data in contents.items():
            z.writestr(name, data)
    with app.app_context():
        with pytest.raises(ValueError, match="checksum"):
            restore_backup(corrupt)
        assert db.session.get(Product, 1).stock == 10


def test_corruption_enters_recovery_and_restores_without_db_login(app, client):
    backup_response(app, client)
    with app.app_context():
        db.session.remove()
        database = Path(db.engine.url.database)
        db.engine.dispose()
    database.write_bytes(b"broken database" * 100)
    assert not service.check_database(database)
    from app import create_app

    recovery = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "ROOT": app.config["ROOT"],
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(database),
        }
    )
    assert recovery.config["RECOVERY_MODE"]
    c = recovery.test_client()
    assert c.get("/login").location == "/recovery"
    tick(recovery)
    state = c.get("/api/recovery/status").json
    chosen = next(f for f in state["files"] if f["healthy"])
    assert b"Emergency Recovery" in c.get("/recovery").data
    data = {
        "source": chosen["source"],
        "name": chosen["name"],
        "username": "admin",
        "password": "wrong",
        "confirm": "RESTORE",
    }
    assert c.post("/recovery", data=data).status_code == 400
    data["password"] = "test-password-123"
    assert c.post("/recovery", data=data).status_code == 202
    tick(recovery)
    assert not recovery.config["RECOVERY_MODE"] and service.check_database(database)
    assert list((app.config["ROOT"] / "instance").glob("corrupt-*"))
    assert (
        c.post(
            "/login", data={"username": "admin", "password": "test-password-123"}
        ).status_code
        == 302
    )
    with recovery.app_context():
        assert db.session.get(Product, 1).stock == 10
        db.session.remove()
        db.engine.dispose()


def test_permissions_password_and_path_validation(app, client):
    backup_response(app, client)
    assert (
        client.post(
            "/settings/restore", data={"password": "wrong", "confirm": "RESTORE"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/settings/restore",
            data={
                "password": "test-password-123",
                "confirm": "RESTORE",
                "source": "Primary",
                "name": "../store.db",
            },
        ).status_code
        == 400
    )
    with app.app_context():
        config = settings()
        # Identical destinations are rejected; nesting and any absolute
        # location (drives, USB, UNC shares) are allowed.
        config["backup_primary"] = str(app.config["ROOT"] / "backups")
        config["backup_secondary"] = str(app.config["ROOT"] / "backups")
        with pytest.raises(ValueError):
            service.validate_config(app.config["ROOT"], config)
    with client.session_transaction() as sess:
        sess["user_id"] = 3
    assert client.get("/api/backups/status").status_code == 403
    assert client.get("/settings/backup-logs").status_code == 403
    assert client.post("/settings/backup").status_code == 403


def test_schedule_survives_restart(app, client):
    with app.app_context():
        save_setting("backup_live", "0")
        save_setting("backup_frequency", "Every 15 Minutes")
        db.session.commit()
    tick(app)
    first = app.extensions["backups"]
    first.next_due = time.time() + 300
    first.persist_schedule()
    replacement = app.extensions["backups"] = service.BackupManager(app)
    tick(app)
    assert abs(replacement.next_due - first.next_due) < 1


def test_invalid_image_cannot_be_reported_as_healthy_backup(app, client):
    backup_response(app, client)
    name = "f" * 32 + ".png"
    (app.config["ROOT"] / "static/uploads" / name).write_bytes(b"damaged image")
    with app.app_context():
        db.session.get(Product, 1).image = name
        db.session.commit()
        results = service.run_backup()
    assert all(r["status"] == "Failed" for r in results)
    assert len(list((app.config["ROOT"] / "backups").glob("*.zip"))) == 1


def test_disk_full_keeps_previous_recovery_points(app, client, monkeypatch):
    backup_response(app, client)
    root = app.config["ROOT"]
    original = {p.name: p.read_bytes() for p in (root / "backups").glob("*.zip")}
    monkeypatch.setattr(service, "probe", lambda path: 0)
    with app.app_context():
        results = service.run_backup()
    assert all(r["status"] == "Failed" and "Disk full" in r["error"] for r in results)
    assert original == {
        p.name: p.read_bytes() for p in (root / "backups").glob("*.zip")
    }


@pytest.mark.parametrize("missing", [False, True])
def test_empty_or_missing_established_database_never_resets_store(app, client, missing):
    backup_response(app, client)
    with app.app_context():
        database = Path(db.engine.url.database)
        db.session.remove()
        db.engine.dispose()
    if missing:
        database.unlink()
    else:
        database.write_bytes(b"")
    from app import create_app

    recovered_app = create_app(
        {
            "TESTING": True,
            "ROOT": app.config["ROOT"],
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(database),
        }
    )
    assert recovered_app.config["RECOVERY_MODE"]
    assert recovered_app.test_client().get("/setup").location == "/recovery"


def test_bulk_stock_change_enqueues_and_csrf_protects_backup(app, client):
    manager = app.extensions["backups"]
    manager.pending = False
    with app.app_context():
        db.session.execute(db.update(Product).where(Product.id == 1).values(stock=9))
        db.session.commit()
    assert manager.pending
    app.config["WTF_CSRF_ENABLED"] = True
    assert client.post("/settings/backup").status_code == 400
    assert (
        client.post(
            "/settings/restore",
            data={"password": "test-password-123", "confirm": "RESTORE"},
        ).status_code
        == 400
    )
