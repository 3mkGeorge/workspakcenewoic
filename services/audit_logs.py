"""Audit logs domain service for StorePro.

Provides audit trail search filtering, facet discovery, and formula-safe CSV export generation.
"""

import csv
from datetime import datetime, timedelta
import io

from models import AuditLog, db
from services.validation import escape_formula


def query_audit_logs(actor="", action="", search_text="", date_from="", date_to=""):
    """Build a filtered SQLAlchemy query for AuditLog records."""
    query = AuditLog.query
    actor = (actor or "").strip()
    if actor:
        query = query.filter(AuditLog.actor == actor)
    action = (action or "").strip()
    if action:
        query = query.filter(AuditLog.action == action)
    q = (search_text or "").strip()
    if q:
        term = "%" + q.replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(
            db.or_(
                AuditLog.details.ilike(term, escape="\\"),
                AuditLog.actor.ilike(term, escape="\\"),
                AuditLog.action.ilike(term, escape="\\"),
            )
        )
    date_from = (date_from or "").strip()
    if date_from:
        try:
            df = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at >= df)
        except ValueError:
            pass
    date_to = (date_to or "").strip()
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(AuditLog.created_at < dt)
        except ValueError:
            pass
    return query.order_by(AuditLog.id.desc())


def get_audit_actors_and_actions():
    """Retrieve distinct lists of actors and actions recorded in audit logs."""
    actors = [
        r[0]
        for r in db.session.execute(
            db.select(AuditLog.actor).distinct().order_by(AuditLog.actor)
        ).all()
        if r[0]
    ]
    actions = [
        r[0]
        for r in db.session.execute(
            db.select(AuditLog.action).distinct().order_by(AuditLog.action)
        ).all()
        if r[0]
    ]
    return actors, actions


def generate_audit_csv_bytes(logs):
    """Generate UTF-8-SIG encoded CSV bytes for audit logs with Excel formula escaping."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["ID", "Timestamp (UTC)", "Actor", "Action", "Details"])
    for l in logs:
        writer.writerow([
            l.id,
            l.created_at.strftime("%Y-%m-%d %H:%M:%S") if l.created_at else "",
            escape_formula(l.actor or ""),
            escape_formula(l.action or ""),
            escape_formula(l.details or ""),
        ])
    return output.getvalue().encode("utf-8-sig")
