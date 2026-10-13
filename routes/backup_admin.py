"""Admin-only asynchronous backup controls and database-independent recovery."""

import time
from uuid import uuid4
from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
)
from werkzeug.security import check_password_hash
from models import BackupLog
from services.dual_backup import NAME, destinations, read_recovery

backup_admin = Blueprint("backup_admin", __name__)


def manager():
    return current_app.extensions["backups"]


def check_password(value, emergency=False):
    service = manager()
    # All recovery attempts share the localhost rate limit, independent of cookies.
    with service.lock:
        attempts = [
            x
            for x in getattr(service, "password_attempts", [])
            if time.monotonic() - x < 60
        ]
        if len(attempts) >= 5:
            raise ValueError("Too many password attempts. Wait one minute.")
        attempts.append(time.monotonic())
        service.password_attempts = attempts
    if emergency:
        username = request.form.get("username", "").strip().lower()
        valid = any(
            a["username"] == username and check_password_hash(a["hash"], value)
            for a in read_recovery(current_app)["admins"]
        )
    else:
        valid = check_password_hash(g.user.password_hash, value)
    if not valid:
        raise ValueError("Administrator password is incorrect.")


def selected_file(config):
    source = request.form.get("source", "")
    name = request.form.get("name", "")
    if source not in ("Primary", "Secondary") or not NAME.fullmatch(name):
        raise ValueError("Choose a backup from Primary or Secondary.")
    folder = destinations(current_app.config["ROOT"], config)[source].resolve()
    path = folder / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != folder:
        raise ValueError("The selected backup is no longer available.")
    return path


@backup_admin.get("/api/backups/status")
def status():
    return jsonify(manager().snapshot())


@backup_admin.post("/api/backups/test")
def test_paths():
    """Verify folder existence, read/write access and disk space (saves nothing)."""
    import os
    import shutil
    from services.core import settings
    from services.dual_backup import (
        destinations,
        probe,
        validate_config,
        NAME,
        stamp,
    )

    data = request.get_json(silent=True) or {}
    config = settings()
    trial = dict(config)
    for key in ("backup_primary", "backup_secondary"):
        if key in data:
            trial[key] = (data[key] or "").strip()[:500]
    validate_config(current_app.config["ROOT"], trial)
    results = []
    for source, folder in destinations(current_app.config["ROOT"], trial).items():
        try:
            if not folder.exists():
                raise ValueError(
                    f"{source} folder does not exist: {folder}. Create it or pick another folder."
                )
            if not folder.is_dir() or folder.is_symlink():
                raise ValueError(f"{source} path is not a folder: {folder}.")
            if not os.access(folder, os.R_OK):
                raise ValueError(f"Read access denied for {source} folder: {folder}.")
            try:
                with os.scandir(folder):
                    pass
            except OSError as exc:
                raise ValueError(f"Cannot read {source} folder: {exc}.")
            free = probe(folder)  # write check: creates and removes a temp file
            try:
                total_free = shutil.disk_usage(folder).free
            except OSError:
                total_free = free
            zips = [
                p
                for p in folder.glob("storepro-*.zip")
                if NAME.fullmatch(p.name) and not p.is_symlink()
            ]
            zips.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
            if total_free <= 0:
                raise ValueError(f"No free disk space on {source} destination.")
            results.append(
                {
                    "source": source,
                    "path": str(folder),
                    "writable": True,
                    "free": total_free,
                    "count": len(zips),
                    "last_backup": stamp(zips[0].stat().st_mtime)
                    if zips
                    else None,
                }
            )
        except (OSError, ValueError) as exc:
            results.append(
                {
                    "source": source,
                    "path": str(folder),
                    "writable": False,
                    "free": 0,
                    "count": 0,
                    "last_backup": None,
                    "error": str(exc),
                }
            )
    return jsonify(destinations=results)


@backup_admin.post("/api/backups/paths")
def save_paths():
    """Persist validated backup destinations, with audit trail."""
    import os
    from services.core import settings, save_setting, audit
    from services.dual_backup import destinations, probe, validate_config

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Send Primary/Secondary paths as JSON.")
    config = settings()
    trial = dict(config)
    values = {}
    for key in ("backup_primary", "backup_secondary"):
        values[key] = (data.get(key, config.get(key, "")) or "").strip()[:500]
        trial[key] = values[key]
    validate_config(current_app.config["ROOT"], trial)
    folders = destinations(current_app.config["ROOT"], trial)
    missing = {
        source: str(folder)
        for source, folder in folders.items()
        if not folder.exists()
    }
    if missing and not data.get("confirm_create"):
        return jsonify(
            error="Backup folder does not exist.",
            needs_confirm=missing,
        ), 409
    errors = {}
    for source, folder in folders.items():
        try:
            # Missing folders are created here only after confirmation.
            folder.mkdir(parents=True, exist_ok=True)
            if not os.access(folder, os.R_OK | os.W_OK):
                raise ValueError(f"Read/write access denied for {source} folder: {folder}.")
            probe(folder)
        except (OSError, ValueError) as exc:
            errors[source] = str(exc)
    if errors:
        return jsonify(error="Backup path validation failed.", details=errors), 400
    changes = []
    for key, label in (
        ("backup_primary", "Primary"),
        ("backup_secondary", "Secondary"),
    ):
        old, new = config.get(key, ""), values[key]
        if old != new:
            save_setting(key, new)
            changes.append(f"{label}: {old or '(installation default)'} → {new or '(installation default)'}")
    if changes:
        audit("Backup paths changed", "; ".join(changes))
        from models import db

        db.session.commit()
        manager().changed()
    return jsonify(message="Backup destinations saved." if changes else "No changes to save.", changes=changes)


@backup_admin.post("/api/backups/defaults")
def reset_defaults():
    from services.core import settings, save_setting, audit
    from models import db

    config = settings()
    changes = []
    for key, label in (
        ("backup_primary", "Primary"),
        ("backup_secondary", "Secondary"),
    ):
        if config.get(key):
            changes.append(f"{label}: {config[key]} → (installation default)")
            save_setting(key, "")
    if changes:
        audit("Backup paths reset", "; ".join(changes))
        db.session.commit()
        manager().changed()
    return jsonify(message="Default destinations restored." if changes else "Already using defaults.", changes=changes)


@backup_admin.get("/settings/backup-logs")
def logs():
    page = BackupLog.query.order_by(BackupLog.id.desc()).paginate(
        page=max(1, request.args.get("page", 1, type=int)), per_page=30, error_out=False
    )
    return render_template("settings/backup_logs.html", title="Backup Logs", page=page)


@backup_admin.route("/recovery", methods=["GET", "POST"])
def recovery():
    if not current_app.config.get("RECOVERY_MODE"):
        return redirect("/login")
    if request.method == "POST":
        check_password(request.form.get("password", ""), emergency=True)
        if request.form.get("confirm") != "RESTORE":
            raise ValueError(
                "Type RESTORE to confirm replacement of the damaged database."
            )
        config = read_recovery(current_app)["config"]
        path = selected_file(config)
        manager().restore(
            path, emergency=True, actor=request.form.get("username", "Administrator")
        )
        session["recovery_authorized"] = True
        return jsonify(
            message="Recovery queued. The original damaged database will be preserved."
        ), 202
    return render_template(
        "settings/recovery.html",
        title="Emergency Recovery",
        recovery=manager().snapshot(),
    )


@backup_admin.get("/api/recovery/status")
def recovery_status():
    if not current_app.config.get("RECOVERY_MODE"):
        return jsonify(restored=True)
    # Public recovery shows health/candidate metadata only, never cached password hashes.
    state = manager().snapshot()
    return jsonify(
        busy=state["busy"],
        message=state["message"],
        files=state["files"],
        warnings=state["warnings"],
    )


def queue_restore():
    check_password(request.form.get("password", ""))
    if request.form.get("confirm") != "RESTORE":
        raise ValueError("Type RESTORE to confirm database replacement.")
    file = request.files.get("backup")
    if file and file.filename:
        folder = current_app.config["ROOT"] / "instance/restore-staging"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (uuid4().hex + ".zip")
        file.save(path)
    else:
        path = selected_file(g.settings)
    try:
        manager().restore(path, actor=g.user.name)
    except Exception:
        if path.parent.name == "restore-staging":
            path.unlink(missing_ok=True)
        raise
    return jsonify(
        message="Restore queued. Validation runs in the background; everyone is signed out when it completes."
    ), 202
