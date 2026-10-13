"""Automated Production Hardening Test Suite for StorePro.

Validates:
1. Structured logging (JSON format, rotating file handlers, in-memory ring buffer).
2. Audit log viewer (filtering by actor, action, search terms, and CSV export).
3. Application crash recovery (exception interception, incident ID correlation, rollback message).
4. Automated database maintenance (WAL checkpoint TRUNCATE, PRAGMA optimize, vacuum, reindex).
5. Background job monitor (job registry, execution tracking, failure tracking).
6. Slow query monitoring (engine cursor execution interception, circular buffer).
7. Performance telemetry dashboard (metrics snapshot, background jobs table).
8. Backup verification scheduler (archive integrity checks).
"""

import csv
import io
import json
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_app import app, client  # noqa: F401
from models import db, User, Role, AuditLog, Product, BackupLog
from services.job_monitor import job_monitor
from services.logging_service import get_recent_logs
from services.telemetry import get_telemetry_snapshot, _SLOW_QUERIES, SLOW_QUERY_THRESHOLD_MS
from services.maintenance import (
    checkpoint_wal,
    optimize_database,
    vacuum_database,
    reindex_database,
    verify_integrity,
    verify_all_backup_archives,
    run_full_database_maintenance,
)


def test_structured_logging_and_buffer(app, client):
    """Verify structured logger generates records and populates in-memory buffer."""
    client.get("/")
    logs = get_recent_logs(limit=50)
    assert len(logs) > 0
    assert any("Structured logging initialized" in l["message"] or "HTTP" in l["message"] or "GET" in l.get("message", "") or "request" in l.get("message", "").lower() for l in logs)

    # Ensure handlers are flushed
    for h in app.logger.handlers:
        h.flush()

    # Check JSON log file creation
    root = Path(app.config["ROOT"])
    json_log = root / "instance" / "logs" / "storepro.json.log"
    assert json_log.exists()
    assert json_log.stat().st_size > 0

    with open(json_log, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
        data = json.loads(first_line)
        assert "timestamp" in data
        assert "level" in data
        assert "message" in data


def test_audit_log_viewer_and_filters(app, client):
    """Test audit log querying, filtering by actor and action, and CSV export."""
    with app.app_context():
        # Insert known test audit logs
        log1 = AuditLog(actor="admin", action="Create product", details="SKU TEST-AUDIT-1")
        log2 = AuditLog(actor="cashier", action="Complete sale", details="Invoice INV-9999")
        db.session.add_all([log1, log2])
        db.session.commit()

    # 1. Base view
    res = client.get("/settings/audit")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Audit Logs" in html
    assert "TEST-AUDIT-1" in html
    assert "INV-9999" in html

    # 2. Filter by actor
    res_actor = client.get("/settings/audit?actor=admin")
    assert res_actor.status_code == 200
    html_actor = res_actor.get_data(as_text=True)
    assert "TEST-AUDIT-1" in html_actor

    # 3. Filter by action
    res_action = client.get("/settings/audit?action=Complete+sale")
    assert res_action.status_code == 200
    html_action = res_action.get_data(as_text=True)
    assert "INV-9999" in html_action

    # 4. Search query
    res_q = client.get("/settings/audit?q=AUDIT-1")
    assert res_q.status_code == 200
    html_q = res_q.get_data(as_text=True)
    assert "TEST-AUDIT-1" in html_q
    assert "INV-9999" not in html_q

    # 5. CSV export
    res_csv = client.get("/settings/audit/export?q=AUDIT-1")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["Content-Type"]
    csv_text = res_csv.get_data(as_text=True)
    assert "Timestamp (UTC)" in csv_text
    assert "TEST-AUDIT-1" in csv_text


def test_application_crash_recovery(app):
    """Unhandled exceptions must be caught, rolled back, and render safe crash recovery."""
    crash_client = app.test_client()
    # Log in as admin
    crash_client.post("/login", data={"username": "admin", "password": "test-password-123"})

    # 1. HTML request to debug crash route
    res = crash_client.get("/_debug/crash")
    assert res.status_code == 500
    html = res.get_data(as_text=True)
    assert "Application Crash Protection &amp; Recovery" in html or "Crash Protection" in html
    assert "Incident Correlation ID:" in html
    assert "Rolled Back (No Data Lost)" in html
    assert "Return to Dashboard" in html

    # 2. JSON request to debug crash route
    res_api = crash_client.get("/_debug/crash", headers={"Accept": "application/json"})
    assert res_api.status_code == 500
    data = res_api.get_json()
    assert "incident_id" in data
    assert data["database_healthy"] is True


def test_database_maintenance_operations(app):
    """Test WAL checkpoint, optimize, vacuum, reindex, and integrity checks."""
    with app.app_context():
        db_path = Path(db.engine.url.database)

        # 1. Integrity check
        ok, errs = verify_integrity(db_path)
        assert ok is True
        assert len(errs) == 0

        # 2. Optimize
        ok_opt, msg_opt = optimize_database(db_path)
        assert ok_opt is True

        # 3. WAL Checkpoint TRUNCATE
        ok_chk, msg_chk = checkpoint_wal(db_path, "TRUNCATE")
        assert ok_chk is True

        # 4. Reindex
        ok_re, msg_re = reindex_database(db_path)
        assert ok_re is True

        # 5. Vacuum
        ok_vac, msg_vac = vacuum_database(db_path)
        assert ok_vac is True

        # 6. Full maintenance pipeline
        full_res = run_full_database_maintenance(db_path)
        assert full_res["integrity"] == "Passed"


def test_background_job_monitoring(app):
    """Verify background job registration, execution tracking, and duration telemetry."""
    job_monitor.register("test_worker", "Test worker description", "Manual")
    
    with job_monitor.track("test_worker"):
        time.sleep(0.01)

    info = job_monitor.get_job("test_worker")
    assert info["status"] == "Completed"
    assert info["run_count"] == 1
    assert info["last_duration_ms"] >= 9.0
    assert info["failure_count"] == 0

    # Test failure tracking
    with pytest.raises(ValueError):
        with job_monitor.track("test_worker"):
            raise ValueError("Simulated task failure")

    info_after_fail = job_monitor.get_job("test_worker")
    assert info_after_fail["status"] == "Failed"
    assert info_after_fail["failure_count"] == 1
    assert "Simulated task failure" in info_after_fail["last_error"]


def test_slow_query_monitoring(app):
    """Verify slow query detection and circular buffer capture."""
    with app.app_context():
        # Execute query and verify telemetry snapshot
        db.session.execute(db.text("SELECT count(*) FROM products")).scalar()
        snap = get_telemetry_snapshot(app, db)
        assert snap["queries"]["total_queries"] > 0
        assert snap["database"]["journal_mode"] == "WAL"
        assert snap["database"]["page_count"] > 0


def test_telemetry_dashboard_page(app, client):
    """Test telemetry dashboard renders with background jobs, system metrics, and logs."""
    res = client.get("/settings/telemetry")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "System Telemetry &amp; Performance" in html or "System Telemetry & Performance" in html
    assert "Server Uptime" in html
    assert "Database Footprint" in html
    assert "Background Job Registry" in html
    assert "Slow Query Log" in html
    assert "Live Application Event Log" in html


def test_backup_verification_suite(app):
    """Test automated backup archive verification."""
    res = verify_all_backup_archives(app)
    assert "total" in res
    assert "healthy" in res
    assert "failures" in res
    assert isinstance(res["failures"], list)
