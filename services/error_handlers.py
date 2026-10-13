"""Centralized HTTP and application error handlers for StorePro.

Provides clean separation of error interception, JSON/HTML differentiation,
database rollback safety, and incident recovery reporting.
"""

import secrets
from pathlib import Path
from datetime import datetime
from flask import render_template, request, jsonify, redirect, g
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import IntegrityError, DatabaseError
from models import db
from services.dual_backup import check_database


def is_ajax_or_api(req):
    """Detect whether request is from an API client or AJAX consumer."""
    return (
        req.path.startswith("/api/")
        or req.is_json
        or req.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in req.headers.get("Accept", "")
        or req.accept_mimetypes.best == "application/json"
    )


def register_error_handlers(app):
    """Register all custom application and HTTP error handlers on the Flask app."""

    @app.errorhandler(ValueError)
    def validation_error(error):
        db.session.rollback()
        if is_ajax_or_api(request):
            return jsonify(error=str(error)), 400
        return render_template("error.html", code=400, message=str(error)), 400

    @app.errorhandler(IntegrityError)
    def integrity_error(error):
        db.session.rollback()
        if is_ajax_or_api(request):
            return jsonify(
                error="This record changed. Refresh the stock and try again."
            ), 409
        return render_template(
            "error.html",
            code=409,
            message="This record conflicts with existing data. SKU, barcode, username and category names must be unique. Reload before trying again.",
        ), 409

    @app.errorhandler(DatabaseError)
    def database_error(error):
        db.session.remove()
        orig = getattr(error, "orig", error)
        err_msg = str(orig).lower()
        if "locked" in err_msg or "busy" in err_msg:
            app.logger.warning(f"Database lock contention encountered: {error}")
            if is_ajax_or_api(request):
                return jsonify(
                    error="The database is currently busy processing another request. Please retry in a moment."
                ), 503
            return render_template(
                "error.html",
                code=503,
                message="The store is currently busy processing another transaction. Please retry in a moment.",
            ), 503

        if not check_database(Path(db.engine.url.database)):
            app.config["RECOVERY_MODE"] = True
            db.engine.dispose()
            app.extensions["backups"].wake.set()
            if is_ajax_or_api(request):
                return jsonify(
                    error="Database corruption detected. Open /recovery to restore a healthy backup."
                ), 503
            return redirect("/recovery")
        app.logger.exception("Database operation failed")
        if is_ajax_or_api(request):
            return jsonify(error="The database is temporarily unavailable. Try again."), 503
        return render_template(
            "error.html",
            code=503,
            message="The database is temporarily unavailable. Try again.",
        ), 503

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        if is_ajax_or_api(request):
            return jsonify(
                error="Your form expired. Refresh this page to restore your draft.",
                code="csrf_expired",
            ), 400
        return render_template(
            "error.html",
            code=400,
            message="Your form expired. Reload the page and try again.",
        ), 400

    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def http_error(error):
        if is_ajax_or_api(request):
            return jsonify(error=str(error.description)), error.code
        return render_template(
            "error.html",
            code=error.code,
            message={
                403: "Your effective permissions do not allow this action.",
                404: "This record or page could not be found.",
                413: "The uploaded file exceeds the 32 MB limit.",
            }[error.code],
        ), error.code

    @app.errorhandler(500)
    @app.errorhandler(Exception)
    def server_error(error):
        db.session.rollback()
        req_id = getattr(g, "request_id", secrets.token_hex(8))
        app.logger.exception(f"Crash recovery intercepted exception [Incident {req_id}]: {str(error)}")
        db_healthy = True
        try:
            db_healthy = check_database(Path(db.engine.url.database))
            if not db_healthy:
                app.config["RECOVERY_MODE"] = True
                db.engine.dispose()
        except Exception:
            db_healthy = False

        if is_ajax_or_api(request):
            return jsonify(
                error="The operation could not be confirmed. An incident report has been logged.",
                incident_id=req_id,
                database_healthy=db_healthy,
            ), 500

        user = getattr(g, "user", None)
        role_name = getattr(getattr(user, "role", None), "name", getattr(user, "role", ""))
        is_admin = bool(user and role_name in ("Admin", "Administrator"))
        import traceback
        details = traceback.format_exc() if is_admin else None

        return render_template(
            "crash_recovery.html",
            req_id=req_id,
            db_healthy=db_healthy,
            is_admin=is_admin,
            details=details,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        ), 500
