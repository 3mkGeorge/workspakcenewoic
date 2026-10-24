"""Settings › Website: publication of products to the Next Chip storefront and sync diagnostics."""

from datetime import datetime, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from models import Product, db
from services.core import audit
from services.web_catalog_sync import load_config, load_state, run_sync, website_status
from services.web_listings import listing_rows, save_listing, update_publication

website = Blueprint("website", __name__)


def _utc(value):
    """ISO-8601 text from the sync state or the website -> naive UTC datetime for the |date filter."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


@website.get("/settings/website")
def page():
    cfg = load_config()
    state = load_state()
    remote, remote_error = (None, None)
    if request.args.get("check") == "1":
        remote, remote_error = website_status(cfg)
    return render_template(
        "settings/website.html",
        title="Website",
        sync_config=cfg.public(),
        state=state,
        when={key: _utc(state.get(key)) for key in ("last_success_at", "last_failure_at")},
        rows=listing_rows(),
        remote=remote,
        remote_when=_utc(remote.get("lastSuccessAt")) if remote else None,
        remote_error=remote_error,
        checked=request.args.get("check") == "1",
    )


@website.post("/settings/website/sync")
def sync_now():
    result = run_sync("manual")
    if result.get("ok"):
        state = result["state"]
        audit("Website sync", f"{state.get('last_result')}: {state.get('last_product_count')} products, snapshot {state.get('last_snapshot_id')}")
        db.session.commit()
        flash("Website catalog synchronized.", "success")
    else:
        audit("Website sync failed", (result.get("error") or "")[:300])
        db.session.commit()
        flash(result.get("error") or "Website sync failed.", "danger")
    return redirect(url_for("website.page"))


@website.post("/settings/website/publish")
def publish():
    with current_app.config["DB_LOCK"]:
        changed = update_publication(request.form, audit)
        db.session.commit()
    flash("Website publication saved." if changed else "No publication changes.", "success" if changed else "info")
    return redirect(url_for("website.page"))


@website.route("/settings/website/products/<int:pid>", methods=["GET", "POST"])
def listing(pid):
    product = db.get_or_404(Product, pid)
    if request.method == "POST":
        with current_app.config["DB_LOCK"]:
            save_listing(product, request.form, audit)
            db.session.commit()
        flash("Website listing saved.", "success")
        return redirect(url_for("website.page"))
    return render_template("settings/website_listing.html", title="Website listing", product=product, listing=product.web_listing, default_max=load_config().max_per_order)
