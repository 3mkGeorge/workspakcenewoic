import os
import secrets
import sqlite3
import threading
from pathlib import Path
from flask import (
    Flask,
    g,
    session,
    request,
    redirect,
    url_for,
    jsonify,
)
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from werkzeug.exceptions import SecurityError
from werkzeug.middleware.proxy_fix import ProxyFix
from models import db, User, now
from services.core import settings


def env_flag(name, default=False):
    """Read a boolean environment switch (1/true/yes/on)."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def trusted_hosts():
    """Host names accepted by Flask's Host-header validation.

    Local defaults keep the existing Windows behaviour. A hosted deployment
    adds its public hostname through the environment instead of disabling the
    check.
    """
    hosts = ["localhost", "127.0.0.1", "[::1]"]
    configured = os.environ.get("STOREPRO_TRUSTED_HOSTS", "")
    hosts.extend(host.strip() for host in configured.split(",") if host.strip())
    render_host = (os.environ.get("RENDER_EXTERNAL_HOSTNAME") or "").strip()
    if render_host:
        hosts.append(render_host)
    if env_flag("STOREPRO_TRUST_PROXY") or "RENDER" in os.environ:
        # A Render service is always reachable at its own onrender.com name.
        hosts.append(".onrender.com")
    return list(dict.fromkeys(hosts))


@event.listens_for(Engine, "connect")
def configure_sqlite(connection, record):
    if isinstance(connection, sqlite3.Connection):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA journal_mode=WAL")


def create_app(test_config=None):
    root = Path(__file__).resolve().parent
    app = Flask(__name__, instance_path=str(root / "instance"))
    app.json.ensure_ascii = False
    for folder in ("instance", "backups", "static/uploads", "static/images"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    key = root / "instance" / "secret.key"
    if not key.exists():
        key.write_text(secrets.token_hex(32), encoding="ascii")
    default_secret = os.environ.get("STOREPRO_SECRET_KEY") or key.read_text().strip()
    default_db_uri = os.environ.get("STOREPRO_DATABASE_URI") or ("sqlite:///" + str(root / "instance" / "store.db"))
    default_max_content = int(os.environ.get("STOREPRO_MAX_CONTENT_LENGTH", 32 * 1024 * 1024))
    default_csrf_timeout = int(os.environ.get("STOREPRO_CSRF_TIME_LIMIT", 28800))
    app.config.update(
        SECRET_KEY=default_secret,
        SQLALCHEMY_DATABASE_URI=default_db_uri,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=default_max_content,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=env_flag("STOREPRO_SECURE_COOKIES"),
        WTF_CSRF_TIME_LIMIT=default_csrf_timeout,
        ROOT=root,
        DB_LOCK=threading.RLock(),
        AUTH_EPOCH=(os.environ.get("STOREPRO_AUTH_EPOCH") or "").strip() or secrets.token_hex(16),
        SETUP_TOKEN=(os.environ.get("STOREPRO_SETUP_TOKEN") or "").strip(),
        TRUSTED_HOSTS=trusted_hosts(),
    )
    if env_flag("STOREPRO_TRUST_PROXY") or "RENDER" in os.environ:
        # Render terminates TLS at its edge proxy. Trust exactly one hop so
        # request.is_secure, redirects and the login limiter see the real values.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    if test_config:
        app.config.update(test_config)
        if "ROOT" in test_config:
            app.config["ROOT"] = Path(test_config["ROOT"])
        elif "SQLALCHEMY_DATABASE_URI" in test_config:
            uri = test_config["SQLALCHEMY_DATABASE_URI"]
            if uri.startswith("sqlite:///"):
                db_p = Path(uri.replace("sqlite:///", ""))
                if db_p.is_absolute() and root not in db_p.parents and db_p.parent != root:
                    app.config["ROOT"] = db_p.parent
    db.init_app(app)
    from services.logging_service import init_structured_logging
    init_structured_logging(app)
    from services.telemetry import register_telemetry_listeners
    register_telemetry_listeners()
    from services.maintenance import initialize_maintenance
    initialize_maintenance(app, start=not app.config.get("TESTING"))
    from services import prices  # Register transactional product price tracking.
    from services.permissions import enforce_request, seed_empty_catalog
    from services.dual_backup import check_database, initialize, read_recovery

    with app.app_context():
        database = Path(db.engine.url.database)
        app.config["RECOVERY_MODE"] = not check_database(database) or (
            not database.exists() and bool(read_recovery(app)["admins"])
        )

    csrf = CSRFProtect()

    @app.before_request
    def prepare():
        import time as _t
        # An unexpected Host header has no URL adapter, so redirecting would
        # crash. Reject it before templates or sessions are touched.
        if isinstance(request.routing_exception, SecurityError):
            return "Bad Request: untrusted Host header.", 400
        g.request_id = secrets.token_hex(8)
        g.start_time = _t.perf_counter()
        g.user = None
        if app.config.get("RECOVERY_MODE"):
            from services.core import DEFAULTS

            g.settings = DEFAULTS.copy()
            if request.endpoint not in (
                "backup_admin.recovery",
                "backup_admin.recovery_status",
                "healthz",
                "static",
            ):
                return redirect(url_for("backup_admin.recovery"))
            return
        g.settings = settings()
        uid = session.get("user_id")
        if uid:
            user = db.session.get(User, uid)
            if (
                user
                and user.active
                and session.get("version") == user.version
                and session.get("epoch") == app.config["AUTH_EPOCH"]
                and now().timestamp() - session.get("last_seen", 0)
                < int(g.settings["session_minutes"]) * 60
            ):
                g.user = user
                if request.endpoint not in (
                    "backup_admin.status",
                    "backup_admin.recovery_status",
                ):
                    session["last_seen"] = now().timestamp()
            else:
                session.clear()
        if not User.query.first() and request.endpoint not in ("auth.setup", "healthz", "static"):
            return redirect(url_for("auth.setup"))
        if (
            request.endpoint
            and request.endpoint not in ("auth.login", "auth.setup", "healthz", "static")
            and not g.user
        ):
            if request.path.startswith("/api/"):
                return jsonify(
                    error="Your session expired. Sign in again.",
                    code="session_expired",
                ), 401
            return redirect(url_for("auth.login"))
        if g.user:
            enforce_request()

    csrf.init_app(app)

    @app.get("/healthz")
    def healthz():
        """Unauthenticated liveness probe used by the hosting platform."""
        healthy = True
        database = "ok"
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            db.session.rollback()
            healthy = False
            database = "unavailable"
        if app.config.get("RECOVERY_MODE"):
            healthy = False
            database = "recovery"
        return (
            jsonify(status="ok" if healthy else "error", database=database),
            200 if healthy else 503,
        )

    @app.teardown_request
    def finish(error=None):
        db.session.remove()

    @app.after_request
    def headers(response):
        if hasattr(g, "request_id"):
            response.headers["X-Request-ID"] = g.request_id
        if hasattr(g, "start_time"):
            import time as _t
            from services.telemetry import record_request_metric
            duration_ms = (_t.perf_counter() - g.start_time) * 1000
            record_request_metric(request.path, request.method, response.status_code, duration_ms)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response

    from services.error_handlers import register_error_handlers
    register_error_handlers(app)

    from services.template_helpers import register_template_helpers
    register_template_helpers(app)

    from routes.auth import auth
    from routes.main import main
    from routes.catalog import catalog
    from routes.transactions import transactions
    from routes.admin import admin
    from routes.reporting import reporting
    from routes.pos import pos
    from routes.price_history import price_history
    from routes.product_media import product_media
    from routes.backup_admin import backup_admin
    from routes.access import access
    from routes.categories import categories
    from routes.archive import archive
    from routes.shipping import shipping
    from routes.orders import orders_hub
    from routes.website import website

    for bp in (
        auth,
        main,
        catalog,
        transactions,
        admin,
        reporting,
        pos,
        price_history,
        product_media,
        categories,
        archive,
        shipping,
        orders_hub,
        backup_admin,
        access,
        website,
    ):
        app.register_blueprint(bp)
    initialize(app, start=False)
    if app.config["RECOVERY_MODE"]:
        if not app.config.get("TESTING") and app.config.get("BACKUP_WORKER", True):
            app.extensions.pop("backups")
            initialize(app)
        return app
    with app.app_context():
        from services.migrations import upgrade_sqlite

        upgrade_sqlite(
            db.engine.url.database, backup=not app.config.get("TESTING", False)
        )
        db.create_all()
        seed_empty_catalog()
        try:
            from services.product_media import migrate_all_legacy

            migrate_all_legacy()
        except Exception:
            app.logger.exception("Product gallery migration failed")
        from services.migrations import install_price_triggers

        with db.engine.begin() as connection:
            install_price_triggers(connection)
    if not app.config.get("TESTING") and app.config.get("BACKUP_WORKER", True):
        app.extensions.pop("backups")
        initialize(app)
    return app


if __name__ == "__main__":
    import logging
    from logging.handlers import RotatingFileHandler
    from waitress import serve
    from services.backups import start_backups
    import os
    from services.process_lock import store_lock
    from services.startup import validate_startup_directory, print_startup_banner

    # 1. Enforce canonical startup directory
    validate_startup_directory()

    with store_lock(Path(__file__).resolve().parent / "instance/server.lock"):
        app = create_app()
        handler = RotatingFileHandler(
            app.config["ROOT"] / "instance" / "application.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        app.logger.addHandler(handler)
        start_backups(app)
        # Website catalog publisher: only this locked server process schedules it.
        from services.web_catalog_sync import start_web_sync

        start_web_sync(app)
        port = int(os.environ.get("STOREPRO_PORT", "5000"))
        host = os.environ.get("STOREPRO_HOST", "127.0.0.1")
        print_startup_banner(app, host=host, port=port)
        serve(
            app,
            host=host,
            port=port,
            threads=4,
            max_request_body_size=32 * 1024 * 1024,
        )
