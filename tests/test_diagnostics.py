import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_app import app, client  # noqa: F401
from datetime import datetime, timedelta
import pytest
from models import db, BackupLog, User, Role, now


def test_dashboard_diagnostics_rendered_for_admin(app, client):
    """Admin with settings.view should see complete system health cards."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "System Diagnostics &amp; Health" in html or "System Diagnostics & Health" in html
    assert "Database Status" in html
    assert "Database Size" in html
    assert "Disk Usage" in html
    assert "Backup Status" in html
    assert "Last Backup Age" in html
    assert "Backup Alerts" in html
    assert "Online" in html


def test_dashboard_failed_backup_alert_banner(app, client):
    """When a failed backup is recorded, an alert banner is shown and alert count is reflected."""
    with app.app_context():
        # Record a failed backup
        failed_log = BackupLog(
            backup_id="test-fail-1",
            kind="Auto",
            reason="Scheduled",
            status="Failed",
            file_size=0,
            location="primary",
            source="Primary",
            error="Simulated disk write error",
        )
        db.session.add(failed_log)
        db.session.commit()

    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Backup Integrity Alert:" in html
    assert "failed backup operation(s) detected" in html
    assert "1 Failed" in html

    # Clean up test log
    with app.app_context():
        BackupLog.query.filter_by(backup_id="test-fail-1").delete()
        db.session.commit()


def test_dashboard_diagnostics_hidden_from_cashier(app):
    """Cashier without settings.view should NOT see internal system health cards."""
    cashier_client = app.test_client()
    res_login = cashier_client.post("/login", data={"username": "cashier", "password": "test-password-123"})
    assert res_login.status_code == 302

    res = cashier_client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "System Diagnostics & Health" not in html
    assert "Disk Usage" not in html
    assert "Database Status" not in html
