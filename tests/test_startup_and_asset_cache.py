"""Tests for startup identity checks, directory validation, asset cache busting, and policies alias."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from app import create_app
from models import User, now
from services.startup import (
    STOREPRO_VERSION,
    get_app_version,
    get_asset_version,
    validate_startup_directory,
    get_startup_identity,
    print_startup_banner,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def isolated_config(tmp_path, **extra):
    """Boot against a private copy of instance/store.db.

    Starting the app runs schema upgrades, so tests must never open the live
    store database directly. The copy is made with plain file reads.
    """
    import shutil

    target = tmp_path / "instance" / "store.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    live = PROJECT_ROOT / "instance" / "store.db"
    for suffix in ("", "-wal"):
        if Path(str(live) + suffix).exists():
            shutil.copyfile(str(live) + suffix, str(target) + suffix)
    return {"TESTING": True, "ROOT": PROJECT_ROOT, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(target), **extra}


@pytest.fixture
def auth_client(tmp_path):
    """Client authenticated with admin privileges for permission-protected routes."""
    app = create_app(isolated_config(tmp_path, WTF_CSRF_ENABLED=False))
    client = app.test_client()
    with app.app_context():
        user = User.query.filter_by(username="george").first()
        if not user:
            user = User.query.first()
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["version"] = user.version
            sess["epoch"] = app.config["AUTH_EPOCH"]
            sess["last_seen"] = now().timestamp()
    return client, app


def test_startup_directory_validation_success():
    """Canonical repository root passes startup validation."""
    current_root = Path(__file__).resolve().parents[1]
    validated = validate_startup_directory(current_root)
    assert validated == current_root.resolve()


def test_startup_directory_validation_missing_files(tmp_path):
    """Empty or partial directories fail validation with a clear error."""
    with pytest.raises(RuntimeError) as exc_info:
        validate_startup_directory(tmp_path)
    assert "missing required file" in str(exc_info.value).lower()


def test_startup_directory_validation_desktop_copy(tmp_path, monkeypatch):
    """Accidental execution from unverified Desktop or Downloads directories fails."""
    monkeypatch.delenv("STOREPRO_ALLOW_DESKTOP_BUILD", raising=False)
    fake_desktop_dir = tmp_path / "Desktop" / "store-app"
    fake_desktop_dir.mkdir(parents=True)
    # Create the required files so missing-file check passes
    for rel_file in ("app.py", "templates/base.html", "static/css/app.css", "static/css/pos.css", "models/__init__.py", "requirements-lock.txt"):
        p = fake_desktop_dir / rel_file
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("test")

    with pytest.raises(RuntimeError) as exc_info:
        validate_startup_directory(fake_desktop_dir)
    assert "unverified desktop or downloads copy" in str(exc_info.value).lower()


def test_startup_directory_validation_canonical_env_mismatch(monkeypatch):
    """STOREPRO_CANONICAL_DIR env mismatch is rejected."""
    current_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("STOREPRO_CANONICAL_DIR", str(current_root / "other_folder"))
    with pytest.raises(RuntimeError) as exc_info:
        validate_startup_directory(current_root)
    assert "directory mismatch" in str(exc_info.value).lower()


def test_startup_identity_metadata(tmp_path):
    """Startup identity correctly reports project root, version, db path, host and port."""
    app = create_app(isolated_config(tmp_path))
    identity = get_startup_identity(app, host="127.0.0.1", port=5000)
    assert identity["version"] == STOREPRO_VERSION
    assert identity["host"] == "127.0.0.1"
    assert identity["port"] == 5000
    assert identity["url"] == "http://127.0.0.1:5000"
    assert "store-app" in identity["project_root"]
    assert "store.db" in identity["database_path"]


def test_print_startup_banner(capsys, tmp_path):
    """Banner prints required startup identity lines."""
    app = create_app(isolated_config(tmp_path))
    print_startup_banner(app, host="127.0.0.1", port=5000)
    captured = capsys.readouterr().out
    assert f"StorePro Local Store Management - v{STOREPRO_VERSION}" in captured
    assert "Project Root :" in captured
    assert "Database     :" in captured
    assert "Listening At : http://127.0.0.1:5000" in captured


def test_static_asset_cache_busting_url_for(auth_client):
    """url_for('static', ...) automatically includes deterministic ?v= query string."""
    _, app = auth_client
    with app.test_request_context():
        from flask import url_for
        app_css_url = url_for("static", filename="css/app.css")
        pos_css_url = url_for("static", filename="css/pos.css")
        router_css_url = url_for("static", filename="css/router.css")

        assert "?v=" in app_css_url
        assert app_css_url.startswith("/static/css/app.css?v=")
        assert "?v=" in pos_css_url
        assert "?v=" in router_css_url

        # Check version value contains app version
        v_val = app_css_url.split("?v=")[1]
        assert v_val.startswith(STOREPRO_VERSION)


def test_rendered_base_html_includes_cache_busting(auth_client):
    """Base HTML output renders version query strings on stylesheet links."""
    client, _ = auth_client
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert 'href="/static/css/app.css?v=' in html
    assert 'href="/static/css/router.css?v=' in html
    assert f"v{STOREPRO_VERSION}" in html


def test_settings_policies_redirects_to_permissions(auth_client):
    """GET /settings/policies redirects to /settings/permissions with 302."""
    client, _ = auth_client
    res = client.get("/settings/policies", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/settings/permissions")


def test_settings_permissions_returns_200(auth_client):
    """GET /settings/permissions continues to return 200 with policies content."""
    client, _ = auth_client
    res = client.get("/settings/permissions")
    assert res.status_code == 200
    assert "Access Policies" in res.text
    assert 'class="breadcrumb' in res.text


def test_existing_static_assets_load_correctly(auth_client):
    """Static assets load cleanly with 200 both with and without ?v= query parameter."""
    client, _ = auth_client
    # Unversioned path
    res_plain = client.get("/static/css/app.css")
    assert res_plain.status_code == 200
    assert "text/css" in res_plain.content_type
    assert ".icon-button" in res_plain.text
    assert ".breadcrumb" in res_plain.text

    # Versioned path with cache buster
    res_versioned = client.get(f"/static/css/app.css?v={STOREPRO_VERSION}")
    assert res_versioned.status_code == 200
    assert res_versioned.text == res_plain.text
