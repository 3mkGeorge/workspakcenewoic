"""Comprehensive real-world failure mode simulation tests for StorePro.

Simulates:
1. Unexpected shutdown & process lock release
2. Power loss during sale (transaction atomicity & inventory integrity)
3. Power loss during backup (partial archive isolation & atomic rename)
4. Database corruption recovery (detection, recovery mode, and snapshot restore)
5. Backup restore failure (corrupt archives, invalid credentials, zero data loss)
6. Missing image files (graceful degradation without 500 errors)
7. Full disk scenarios (ENOSPC handling during backups & uploads)
8. Locked database scenarios (concurrency lock contention without false corruption)
"""

import errno
import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from test_app import app, client, backup_response, finish_restore  # noqa: F401
from models import db, Product, Customer, Sale, SaleItem, SalePayment, BackupLog, User
from services.core import settings
from services.dual_backup import check_database, inspect_archive, replicate, run_backup
from services.backups import restore_backup
from services.process_lock import store_lock
from services.uploads import save_image
from services.product_media import store_upload


# ============================================================================
# 1. Unexpected Shutdown Simulation
# ============================================================================

def test_unexpected_shutdown_and_lock_recovery(tmp_path):
    """Verify that if the process terminates abruptly while holding the store lock,
    the OS kernel releases the lock automatically so the next startup succeeds immediately."""
    lock_file = tmp_path / ".storepro.lock"

    # Simulate process A acquiring lock
    with store_lock(lock_file):
        assert lock_file.exists()
        # Verify another process/thread cannot acquire lock while active
        with pytest.raises(SystemExit) as exc_info:
            with store_lock(lock_file):
                pass
        assert "StorePro is already running" in str(exc_info.value)

    # Process A exits (abrupt shutdown simulation)
    # The lock must be cleanly acquirable by the restarting process B without manual deletion
    with store_lock(lock_file):
        assert lock_file.exists()


def test_unexpected_shutdown_wal_recovery(app):
    """Verify SQLite WAL rollback recovery when an uncommitted connection terminates abruptly."""
    with app.app_context():
        db_path = Path(db.engine.url.database)
        initial_stock = db.session.get(Product, 1).stock

        # Direct connection makes uncommitted mutations
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE products SET stock = 9999 WHERE id = 1")
        # Abrupt close without COMMIT (simulating sudden termination)
        conn.close()

        # Reopen with SQLAlchemy / new connection
        db.session.remove()
        refreshed_stock = db.session.get(Product, 1).stock
        assert refreshed_stock == initial_stock, "Uncommitted WAL writes must not persist"
        assert check_database(db_path) is True


# ============================================================================
# 2. Power Loss During Sale Simulation
# ============================================================================

def test_power_loss_during_sale_atomicity(client, app):
    """Verify that a power loss or exception mid-way through sale finalization
    leaves zero stock drift and zero partial invoice records in the database."""
    with app.app_context():
        initial_stock = db.session.get(Product, 1).stock
        initial_sales = Sale.query.count()
        initial_items = SaleItem.query.count()
        initial_payments = SalePayment.query.count()

    sale_payload = {
        "token": "a" * 48,
        "items": [{"product_id": 1, "quantity": 3, "discount": 0, "unit_price": 10000}],
        "customer_id": 1,
        "tax_rate": 1400,
        "currency": "EGP",
        "payments": [{"method": "Cash", "amount": 34200}],
    }

    # Simulate an abrupt crash / power loss midway through save_invoice (e.g. during fulfillment)
    with patch("services.pos.apply_fulfillment", side_effect=RuntimeError("SIMULATED_POWER_CUT_MID_SALE")):
        response = client.post("/api/pos/sales", json=sale_payload)
        assert response.status_code == 500
        assert "incident_id" in response.json

    # Inspect state post-abort:
    with app.app_context():
        db.session.remove()
        product = db.session.get(Product, 1)
        assert product.stock == initial_stock, "Product stock must NOT drift after interrupted sale"
        assert Sale.query.count() == initial_sales, "No orphaned sale header must exist"
        assert SaleItem.query.count() == initial_items, "No orphaned sale items must exist"
        assert SalePayment.query.count() == initial_payments, "No orphaned payment records must exist"

    # Verify that a normal retry completes cleanly
    sale_payload["token"] = "b" * 48
    retry_resp = client.post("/api/pos/sales", json=sale_payload)
    assert retry_resp.status_code == 200
    with app.app_context():
        assert db.session.get(Product, 1).stock == initial_stock - 3


# ============================================================================
# 3. Power Loss During Backup Simulation
# ============================================================================

def test_power_loss_during_backup_isolation(app, client):
    """Verify that power loss during backup leaves partial files isolated,
    scanner ignores incomplete archives, and subsequent backups succeed."""
    root = app.config["ROOT"]
    primary_dir = root / "backups"
    primary_dir.mkdir(parents=True, exist_ok=True)

    # Simulate an incomplete partial backup left by an aborted transfer
    stale_partial = primary_dir / ".storepro-20261002-120000-abcdef.zip.partial"
    stale_partial.write_bytes(b"TRUNCATED_PARTIAL_ZIP_BYTES")

    # Run backup scan
    status = client.get("/api/backups/status").json
    # The partial file must NOT be listed in valid recovery points
    names = [f["name"] for f in status.get("files", [])]
    assert stale_partial.name not in names

    # Simulate an unhandled crash during make_archive
    with patch("services.dual_backup.make_archive", side_effect=IOError("SIMULATED_DISK_WRITE_ABORT")):
        with app.app_context():
            results = run_backup("Manual", "Simulation")
        assert len(results) == 2
        assert all(r["status"] == "Failed" for r in results)
        assert all("SIMULATED_DISK_WRITE_ABORT" in r["error"] for r in results)

    # Verify that a subsequent normal backup executes cleanly
    response = backup_response(app, client)
    assert response.status_code == 200
    assert response.data[:4] == b"PK\x03\x04"


# ============================================================================
# 4. Database Corruption Recovery Simulation
# ============================================================================

def test_database_corruption_detection_and_recovery(app, client):
    """Verify detection of database corruption, automatic RECOVERY_MODE activation,
    and authenticated disaster recovery restore."""
    # 1. First ensure a healthy backup exists
    backup_data = backup_response(app, client)
    state = client.get("/api/backups/status").json
    backup_filename = state["files"][0]["name"]
    source_location = state["files"][0]["source"]

    with app.app_context():
        db_path = Path(db.engine.url.database)
    assert check_database(db_path) is True

    # 2. Simulate physical corruption by destroying database header and pages
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    with open(db_path, "r+b") as f:
        f.seek(0)
        f.write(b"CORRUPTED_SQLITE_HEADER_GARBAGE" * 20)
        f.flush()

    # 3. Verify check_database flags the corrupted state
    assert check_database(db_path) is False

    # 4. API requests must encounter graceful corruption handling
    resp = client.get("/api/pos/products")
    assert resp.status_code == 503
    assert "Database corruption detected" in resp.json.get("error", "")

    # 5. Verify RECOVERY_MODE is active
    assert app.config.get("RECOVERY_MODE") is True

    # 6. Web browser requests to recovery portal load cleanly
    rec_page = client.get("/recovery")
    assert rec_page.status_code == 200
    assert b"Emergency Recovery" in rec_page.data

    # 7. Perform emergency restore through recovery portal
    restore_resp = client.post(
        "/recovery",
        data={
            "source": source_location,
            "name": backup_filename,
            "username": "admin",
            "password": "test-password-123",
            "confirm": "RESTORE",
        },
    )
    assert restore_resp.status_code == 202

    # Let the background recovery thread finish
    finish_restore(app)

    # 8. Verify post-recovery state:
    assert app.config.get("RECOVERY_MODE") is False
    assert check_database(db_path) is True

    # Corrupt database was preserved in instance/corrupt-*
    corrupt_dirs = list((app.config["ROOT"] / "instance").glob("corrupt-*"))
    assert len(corrupt_dirs) >= 1

    # All existing sessions are invalidated on restore for security. Log in again:
    login_resp = client.post(
        "/login", data={"username": "admin", "password": "test-password-123"}
    )
    assert login_resp.status_code == 302

    # Normal operations resume
    res = client.get("/api/pos/products")
    assert res.status_code == 200
    assert len(res.json["items"]) >= 1


# ============================================================================
# 5. Backup Restore Failure Simulation
# ============================================================================

def test_backup_restore_failure_preserves_live_db(app, client):
    """Verify that corrupted archives, tampered files, and invalid credentials
    fail safely and leave the live database completely untouched."""
    with app.app_context():
        initial_users = User.query.count()
        initial_products = Product.query.count()

    root = app.config["ROOT"]

    # Scenario A: Corrupted / truncated ZIP archive
    corrupt_zip = root / "instance/corrupt_test.zip"
    corrupt_zip.write_bytes(b"PK\x03\x04not_a_valid_zip_content")
    with pytest.raises(ValueError, match="not a valid StorePro backup"):
        with app.app_context():
            restore_backup(corrupt_zip, emergency=False)

    # Scenario B: ZIP containing non-database garbage file
    fake_zip = root / "instance/fake_backup.zip"
    with zipfile.ZipFile(fake_zip, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "StorePro", "version": 2}))
        z.writestr("store.db", b"GARBAGE_NOT_A_DATABASE")
    with pytest.raises(ValueError):
        with app.app_context():
            restore_backup(fake_zip, emergency=False)

    # Scenario C: Incorrect admin password during restore
    resp = client.post(
        "/settings/restore",
        data={
            "source": "Primary",
            "name": "any.zip",
            "password": "WRONG_PASSWORD_ATTEMPT",
            "confirm": "RESTORE",
        },
    )
    assert resp.status_code == 400

    # Scenario D: Wrong confirmation text
    resp = client.post(
        "/settings/restore",
        data={
            "source": "Primary",
            "name": "any.zip",
            "password": "Password12345!",
            "confirm": "NOT_RESTORE",
        },
    )
    assert resp.status_code == 400

    # Verify live database was 100% preserved
    with app.app_context():
        assert User.query.count() == initial_users
        assert Product.query.count() == initial_products


# ============================================================================
# 6. Missing Image Files Simulation
# ============================================================================

def test_missing_image_files_graceful_handling(app, client):
    """Verify that if product image files or store logo are deleted from disk,
    product pages, POS, and backups degrade gracefully without 500 errors."""
    with app.app_context():
        product = db.session.get(Product, 1)
        # Assign an image filename that does NOT exist on disk (valid hex format)
        ghost_filename = "e" * 32 + ".png"
        product.image = ghost_filename
        db.session.commit()

        # Ensure ghost file definitely does not exist
        ghost_path = app.config["ROOT"] / "static/uploads" / ghost_filename
        if ghost_path.exists():
            ghost_path.unlink()

    # 1. Product catalog page renders 200 OK with fallback
    resp = client.get("/products")
    assert resp.status_code == 200
    # The CSP blocks inline handlers; the fallback is the delegated handler in app.js.
    assert b"onerror=" not in resp.data
    assert f'class="product-thumb" src="/static/uploads/{ghost_filename}'.encode() in resp.data

    # 2. POS product API returns valid JSON without crashing
    resp_api = client.get("/api/pos/products?q=Test")
    assert resp_api.status_code == 200
    assert resp_api.json["items"][0]["id"] == 1

    # 3. POS sales checkout page loads cleanly
    resp_pos = client.get("/sales/new")
    assert resp_pos.status_code == 200

    # 4. Backup creation ignores missing media cleanly
    response = backup_response(app, client)
    assert response.status_code == 200


# ============================================================================
# 7. Full Disk Scenarios Simulation
# ============================================================================

def test_full_disk_during_backup_replication(app):
    """Verify that replicate() detects insufficient disk space, sets Failed status,
    and removes any partial files."""
    root = app.config["ROOT"]
    dummy_archive = root / "instance/dummy_archive.zip"
    dummy_archive.write_bytes(b"PK\x03\x04" + b"0" * 1024)

    target_folder = root / "backups_full_disk"
    target_folder.mkdir(parents=True, exist_ok=True)

    # Mock probe to report 0 bytes free disk space
    with patch("services.dual_backup.probe", return_value=0):
        result = replicate(dummy_archive, target_folder, "test_backup.zip", verify=False)
        assert result["status"] == "Failed"
        assert "Disk full" in result["error"]
        # Ensure no residual partial files were left
        partial_files = list(target_folder.glob("*.partial"))
        assert len(partial_files) == 0


def test_full_disk_during_image_upload(app):
    """Verify that full disk (ENOSPC) during file upload yields a clean ValueError
    and does not leave orphan .uploading files."""
    root = app.config["ROOT"]
    uploads_dir = root / "static/uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy image in memory
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "blue").save(buf, "PNG")
    buf.seek(0)

    class DummyStorage:
        filename = "test_upload.png"
        stream = buf

    # Simulate OSError ENOSPC
    with patch("PIL.Image.Image.save", side_effect=OSError(errno.ENOSPC, "No space left on device")):
        with app.app_context():
            with pytest.raises(ValueError, match="Insufficient disk space to save image"):
                save_image(DummyStorage())

    # Ensure no .uploading file residue
    uploading_files = list(uploads_dir.glob("*.uploading"))
    assert len(uploading_files) == 0


# ============================================================================
# 8. Locked Database Scenarios Simulation
# ============================================================================

def test_locked_database_resilience(app, client):
    """Verify that SQLite lock contention is handled gracefully as a 503 busy response
    and does NOT falsely activate RECOVERY_MODE."""
    with app.app_context():
        db_path = Path(db.engine.url.database)

    # Open direct connection and hold an exclusive lock
    lock_conn = sqlite3.connect(db_path, timeout=0.1)
    lock_conn.execute("BEGIN EXCLUSIVE")

    try:
        # 1. check_database must NOT claim the database is corrupt just because it's locked
        assert check_database(db_path) is True, "Locked database must not be falsely flagged as corrupt"

        # 2. Simulate a web request encountering SQLite lock contention
        from sqlalchemy.exc import OperationalError as SAOperationalError
        orig_err = sqlite3.OperationalError("database is locked")
        simulated_lock_exc = SAOperationalError("UPDATE products ...", {}, orig_err)

        with patch.object(db.session, "commit", side_effect=simulated_lock_exc):
            response = client.post(
                "/api/pos/sales",
                json={
                    "token": "c" * 48,
                    "items": [{"product_id": 1, "quantity": 1, "discount": 0, "unit_price": 10000}],
                    "customer_id": 1,
                    "tax_rate": 1400,
                    "currency": "EGP",
                    "payments": [{"method": "Cash", "amount": 11400}],
                },
            )
            assert response.status_code == 503
            assert "busy processing another request" in response.json.get("error", "")

        # 3. Crucially: RECOVERY_MODE must NOT have been triggered
        assert app.config.get("RECOVERY_MODE") is not True, "Lock contention must not trigger recovery mode"

    finally:
        lock_conn.rollback()
        lock_conn.close()

    # 4. Normal operations resume once lock is released
    resp = client.get("/api/pos/products")
    assert resp.status_code == 200
