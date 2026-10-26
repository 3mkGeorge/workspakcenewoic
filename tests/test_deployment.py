"""Deployment-oriented checks: health probe, host validation, setup code,
secure cookies and the Render start script.

These tests use temporary databases, like the rest of the suite.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from models import Role, User, db

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app_factory(tmp_path):
    apps = []

    def make(**overrides):
        config = {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "ROOT": tmp_path,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "store.db"),
        }
        config.update(overrides)
        app = create_app(config)
        apps.append(app)
        return app

    yield make
    for app in apps:
        with app.app_context():
            from services.logging_service import shutdown_structured_logging

            shutdown_structured_logging(app)
            db.session.remove()
            db.engine.dispose()


def add_admin(app, username="admin", password="test-password-123"):
    with app.app_context():
        role = Role(name="Admin")
        db.session.add(role)
        db.session.flush()
        db.session.add(
            User(
                name="Admin",
                username=username,
                password_hash=generate_password_hash(password),
                role_id=role.id,
            )
        )
        db.session.commit()


def test_healthz_is_public_before_first_run(app_factory):
    app = app_factory()
    client = app.test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "ok"}
    # The normal first-run redirect still applies to everything else.
    landing = client.get("/")
    assert landing.status_code == 302
    assert "/setup" in landing.headers["Location"]


def test_healthz_does_not_require_a_session(app_factory):
    app = app_factory()
    add_admin(app)

    response = app.test_client().get("/healthz")

    assert response.status_code == 200
    assert response.get_json()["database"] == "ok"


def test_setup_requires_configured_code(app_factory, monkeypatch):
    monkeypatch.setenv("STOREPRO_SETUP_TOKEN", "setup-code-123")
    app = app_factory()
    client = app.test_client()

    page = client.get("/setup")
    assert page.status_code == 200
    assert b'name="setup_token"' in page.data

    form = {
        "name": "Owner",
        "username": "owner",
        "password": "a-long-password-123",
    }
    missing = client.post("/setup", data=form)
    assert missing.status_code == 403
    wrong = client.post("/setup", data={**form, "setup_token": "nope"})
    assert wrong.status_code == 403
    with app.app_context():
        assert User.query.count() == 0

    accepted = client.post(
        "/setup", data={**form, "setup_token": "setup-code-123"}
    )
    assert accepted.status_code == 302
    assert "/login" in accepted.headers["Location"]
    with app.app_context():
        user = User.query.one()
        assert user.username == "owner"
        assert user.role.name == "Admin"


def test_setup_has_no_code_field_for_local_installations(app_factory, monkeypatch):
    monkeypatch.delenv("STOREPRO_SETUP_TOKEN", raising=False)
    app = app_factory()

    page = app.test_client().get("/setup")

    assert page.status_code == 200
    assert b'name="setup_token"' not in page.data


def test_secure_cookie_and_stable_auth_epoch(app_factory, monkeypatch):
    monkeypatch.setenv("STOREPRO_SECURE_COOKIES", "1")
    monkeypatch.setenv("STOREPRO_AUTH_EPOCH", "deployment-epoch")
    app = app_factory()
    add_admin(app)

    assert app.config["AUTH_EPOCH"] == "deployment-epoch"
    response = app.test_client().post(
        "/login",
        data={"username": "admin", "password": "test-password-123"},
    )

    cookie = response.headers.get("Set-Cookie", "")
    assert response.status_code == 302
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie


def test_host_header_must_be_trusted(app_factory, monkeypatch):
    monkeypatch.setenv("STOREPRO_TRUST_PROXY", "1")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "storepro.onrender.com")
    app = app_factory()
    client = app.test_client()

    assert client.get("/healthz", headers={"Host": "evil.example"}).status_code == 400
    assert (
        client.get("/healthz", headers={"Host": "storepro.onrender.com"}).status_code
        == 200
    )
    assert client.get("/healthz", headers={"Host": "localhost"}).status_code == 200


def test_custom_domain_can_be_added(app_factory, monkeypatch):
    monkeypatch.setenv("STOREPRO_TRUSTED_HOSTS", "shop.example.com")
    app = app_factory()

    response = app.test_client().get(
        "/healthz", headers={"Host": "shop.example.com"}
    )

    assert response.status_code == 200


def test_proxy_fix_only_when_requested(app_factory, monkeypatch):
    monkeypatch.delenv("STOREPRO_TRUST_PROXY", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    plain = app_factory()
    assert plain.wsgi_app.__class__.__name__ != "ProxyFix"

    monkeypatch.setenv("STOREPRO_TRUST_PROXY", "1")
    proxied = app_factory()
    assert proxied.wsgi_app.__class__.__name__ == "ProxyFix"


def test_wsgi_entrypoint_starts_without_debug(tmp_path):
    database = tmp_path / "wsgi.db"
    env = {
        **os.environ,
        "STOREPRO_DATABASE_URI": "sqlite:///" + str(database),
        "STOREPRO_SECRET_KEY": "test-secret-key-for-wsgi-import",
        "STOREPRO_AUTH_EPOCH": "test-epoch",
        "STOREPRO_SECURE_COOKIES": "1",
    }
    env.pop("FLASK_DEBUG", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import wsgi; print(wsgi.app.debug); print(wsgi.app.config['SESSION_COOKIE_SECURE'])",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[:2] == ["False", "True"]
    assert database.exists()


def test_database_survives_an_app_restart(tmp_path):
    database = "sqlite:///" + str(tmp_path / "restart.db")
    first = create_app(
        {
            "TESTING": True,
            "ROOT": tmp_path,
            "SQLALCHEMY_DATABASE_URI": database,
        }
    )
    add_admin(first, username="persisted")
    with first.app_context():
        from services.logging_service import shutdown_structured_logging

        shutdown_structured_logging(first)
        db.session.remove()
        db.engine.dispose()

    second = create_app(
        {
            "TESTING": True,
            "ROOT": tmp_path,
            "SQLALCHEMY_DATABASE_URI": database,
        }
    )
    try:
        with second.app_context():
            assert User.query.filter_by(username="persisted").one()
    finally:
        with second.app_context():
            from services.logging_service import shutdown_structured_logging

            shutdown_structured_logging(second)
            db.session.remove()
            db.engine.dispose()


def test_render_blueprint_uses_paid_disk_and_production_server():
    blueprint = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")
    start_script = (PROJECT_ROOT / "scripts" / "render_start.sh").read_text(
        encoding="utf-8"
    )
    gunicorn = (PROJECT_ROOT / "gunicorn.conf.py").read_text(encoding="utf-8")

    assert "healthCheckPath: /healthz" in blueprint
    assert "mountPath: /var/data" in blueprint
    assert "plan: free" not in blueprint
    assert "generateValue: true" in blueprint
    assert "startCommand: bash scripts/render_start.sh" in blueprint
    assert 'exec "$GUNICORN"' in start_script
    assert "unset GUNICORN_CMD_ARGS" in start_script
    assert "workers = 1" in gunicorn
    assert '"0.0.0.0:"' in gunicorn


@pytest.mark.skipif(os.name == "nt", reason="symlink test runs on Linux")
def test_render_start_script_links_persistent_folders(tmp_path):
    app_dir = tmp_path / "app"
    (app_dir / "scripts").mkdir(parents=True)
    shutil.copy(
        PROJECT_ROOT / "scripts" / "render_start.sh", app_dir / "scripts"
    )
    uploads = app_dir / "static" / "uploads" / "products"
    uploads.mkdir(parents=True)
    (uploads / "demo.jpg").write_bytes(b"demo")
    secondary = app_dir / "backups-secondary"
    secondary.mkdir()
    (secondary / "old-sample.zip").write_bytes(b"sample")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gunicorn = fake_bin / "gunicorn"
    fake_gunicorn.write_text("#!/bin/sh\necho gunicorn-started\n", encoding="utf-8")
    fake_gunicorn.chmod(0o755)

    data = tmp_path / "data"
    env = {
        **os.environ,
        "STOREPRO_DATA_DIR": str(data),
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
    }
    for _ in range(2):  # idempotent on redeploy
        result = subprocess.run(
            ["bash", str(app_dir / "scripts" / "render_start.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert "gunicorn-started" in result.stdout

    assert (app_dir / "instance").is_symlink()
    assert (app_dir / "backups").is_symlink()
    assert (app_dir / "backups-secondary").is_symlink()
    assert (app_dir / "static" / "uploads").is_symlink()
    assert (data / "uploads" / "products" / "demo.jpg").read_bytes() == b"demo"
    # Sample archives shipped in Git are not treated as business data.
    assert not (data / "backups-secondary" / "old-sample.zip").exists()
