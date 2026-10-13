"""Administrative routes: store configuration, user management, audit trails, and maintenance."""

from pathlib import Path
from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from models import Expense, Role, User, db
from services.audit_logs import (
    generate_audit_csv_bytes,
    get_audit_actors_and_actions,
    query_audit_logs,
)
from services.core import audit
from services.dual_backup import NAME, destinations
from services.settings import (
    create_expense_record,
    save_managed_user,
    update_account_password,
    update_store_settings,
)

admin = Blueprint("admin", __name__)


@admin.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        update_store_settings(
            request.form,
            request.files,
            current_app.config["ROOT"],
            g.settings,
        )
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings_page"))
    return render_template(
        "settings/index.html",
        title="Settings",
        backup_state=current_app.extensions["backups"].snapshot(),
    )


@admin.post("/settings/backup")
def backup():
    queued = current_app.extensions["backups"].enqueue()
    return jsonify(
        message="Backup queued for both locations."
        if queued
        else "A backup or restore is already running."
    ), 202 if queued else 409


@admin.get("/settings/backups/<name>")
def download_backup(name):
    source = request.args.get("source", "Primary")
    if not NAME.fullmatch(name) or source not in ("Primary", "Secondary"):
        abort(404)
    folder = destinations(current_app.config["ROOT"], g.settings)[source].resolve()
    path = folder / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != folder:
        abort(404)
    return send_file(path, as_attachment=True)


@admin.post("/settings/restore")
def restore():
    from routes.backup_admin import queue_restore

    return queue_restore()


@admin.route("/settings/users", methods=["GET", "POST"])
def users():
    if request.method == "POST":
        save_managed_user(request.form)
        flash(
            "User saved. Existing sessions for this account have been invalidated.",
            "success",
        )
        return redirect(url_for("admin.users"))
    return render_template(
        "settings/users.html",
        title="Users & Roles",
        users=User.query.all(),
        roles=Role.query.all(),
        edit=db.session.get(User, request.args.get("edit", type=int))
        if request.args.get("edit")
        else None,
    )


@admin.route("/account", methods=["GET", "POST"])
def account():
    if request.method == "POST":
        update_account_password(
            g.user,
            request.form.get("current_password", ""),
            request.form.get("password"),
        )
        session.clear()
        return redirect(url_for("auth.login"))
    return render_template("settings/account.html", title="Security")


@admin.get("/settings/audit")
def audit_logs():
    actors, actions = get_audit_actors_and_actions()
    page = query_audit_logs(
        actor=request.args.get("actor", ""),
        action=request.args.get("action", ""),
        search_text=request.args.get("q", ""),
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
    ).paginate(
        page=max(1, request.args.get("page", 1, type=int)), per_page=30, error_out=False
    )
    return render_template(
        "settings/audit.html",
        title="Audit Logs",
        page=page,
        actors=actors,
        actions=actions,
    )


@admin.get("/settings/audit/export")
def export_audit_logs():
    logs = query_audit_logs(
        actor=request.args.get("actor", ""),
        action=request.args.get("action", ""),
        search_text=request.args.get("q", ""),
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
    ).limit(5000).all()
    csv_bytes = generate_audit_csv_bytes(logs)
    resp = Response(csv_bytes, mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=StorePro-Audit-Logs.csv"
    return resp


@admin.get("/settings/telemetry")
def telemetry():
    from services.telemetry import get_telemetry_snapshot
    from services.job_monitor import job_monitor
    from services.logging_service import get_recent_logs

    snapshot = get_telemetry_snapshot(current_app, db)
    jobs = job_monitor.get_all_jobs()
    recent_logs = get_recent_logs(limit=50)

    return render_template(
        "settings/telemetry.html",
        title="System Telemetry",
        snapshot=snapshot,
        jobs=jobs,
        recent_logs=recent_logs,
    )


@admin.post("/settings/maintenance/run")
def run_maintenance():
    from services.maintenance import (
        checkpoint_wal,
        optimize_database,
        vacuum_database,
        reindex_database,
        run_full_database_maintenance,
    )
    from services.job_monitor import job_monitor

    action = request.form.get("action", "full")
    db_path = current_app.config.get("ROOT", Path(".")) / "instance" / "store.db"

    with job_monitor.track("db_maintenance", f"Manual {action}"):
        if action == "checkpoint":
            _ok, msg = checkpoint_wal(db_path, "TRUNCATE")
        elif action == "optimize":
            _ok, msg = optimize_database(db_path)
        elif action == "vacuum":
            _ok, msg = vacuum_database(db_path)
        elif action == "reindex":
            _ok, msg = reindex_database(db_path)
        else:
            res = run_full_database_maintenance(db_path)
            msg = str(res)

    audit("Database maintenance", f"Executed {action}: {msg}")
    db.session.commit()
    flash(f"Maintenance action '{action}' completed.", "success")
    return redirect(url_for("admin.telemetry"))


@admin.post("/settings/backup/verify-all")
def verify_backups_now():
    from services.maintenance import verify_all_backup_archives
    from services.job_monitor import job_monitor

    with job_monitor.track("backup_verifier", "Manual verification"):
        res = verify_all_backup_archives(current_app)

    audit(
        "Backup verification",
        f"Verified {res['healthy']}/{res['total']} backups. Failures: {len(res['failures'])}",
    )
    db.session.commit()
    if res["failures"]:
        flash(f"Warning: {len(res['failures'])} backup archive(s) failed verification.", "danger")
    else:
        flash(f"All {res['healthy']} backup archive(s) verified successfully.", "success")
    return redirect(url_for("admin.telemetry"))


@admin.route("/expenses", methods=["GET", "POST"])
def expenses():
    if request.method == "POST":
        create_expense_record(request.form, g.settings["currency"])
        return redirect(url_for("admin.expenses"))
    page = Expense.query.order_by(Expense.id.desc()).paginate(
        page=max(1, request.args.get("page", 1, type=int)), per_page=20, error_out=False
    )
    return render_template("expenses.html", title="Expenses", page=page)
