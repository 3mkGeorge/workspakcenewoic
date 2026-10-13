"""ERP-style category management API endpoints.

Thin routing layer that delegates business logic to services.categories.
"""

from flask import Blueprint, jsonify, request

from models import Category, db
from services.categories import (
    create_category_record,
    delete_category_record,
    diagnose_category_usage,
    merge_categories_records,
    purge_category_record,
    serialize,
    stats_query,
    update_category_record,
)

categories = Blueprint("categories", __name__)


@categories.get("/api/categories")
def list_categories():
    q = (request.args.get("q") or "").strip().lower()
    rows = stats_query().all()
    items = [serialize(r) for r in rows]
    if q:
        items = [i for i in items if q in i["name"].lower()]
    return jsonify(categories=items, total=len(items))


@categories.post("/api/categories")
def create_category():
    data = request.get_json(silent=True) or {}
    category = create_category_record(data)
    return jsonify(category=serialize((category, 0, 0, 0, 0))), 201


@categories.post("/api/categories/<int:cid>")
def update_category(cid):
    category = db.get_or_404(Category, cid)
    data = request.get_json(silent=True) or {}
    updated_row = update_category_record(category, data)
    return jsonify(category=serialize(updated_row))


@categories.post("/api/categories/merge")
def merge_categories():
    data = request.get_json(silent=True) or {}
    try:
        source_id = int(data.get("source_id"))
        target_id = int(data.get("target_id"))
    except (TypeError, ValueError):
        raise ValueError("Choose a source and a target category.")
    moved, target_id = merge_categories_records(source_id, target_id)
    return jsonify(merged=True, moved=moved, target_id=target_id)


@categories.post("/api/categories/<int:cid>/delete")
def delete_category(cid):
    category = db.get_or_404(Category, cid)
    data = request.get_json(silent=True) or {}
    delete_category_record(category, data)
    return jsonify(deleted=True)


@categories.post("/api/categories/<int:cid>/purge")
def purge_category(cid):
    """Delete archived products (history-free only) and their category."""
    category = db.get_or_404(Category, cid)
    purged = purge_category_record(category)
    return jsonify(deleted=True, purged=purged)


@categories.get("/api/categories/<int:cid>")
def get_category(cid):
    row = stats_query().filter(Category.id == cid).first_or_404()
    item = serialize(row)
    usage = diagnose_category_usage(cid)
    item["blocking"] = [
        {"id": pid, "name": pname, "active": bool(active)}
        for pid, pname, active in usage[:20]
    ]
    return jsonify(category=item)
