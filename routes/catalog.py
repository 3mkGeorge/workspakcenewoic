from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    g,
    abort,
    jsonify,
    current_app,
)
from models import (
    Category,
    Customer,
    InventoryMovement,
    Product,
    ProductImage,
    Purchase,
    PurchaseItem,
    ShippingOrder,
    Supplier,
    db,
)
from services.analytics import stock_stats
from services.core import audit, cents, integer, move, required
from services.inventory import apply_inventory_adjustment
from services.uploads import save_image

catalog = Blueprint("catalog", __name__)


def product_query():
    from sqlalchemy.orm import joinedload

    query = Product.query.options(
        joinedload(Product.category),
        joinedload(Product.supplier),
    ).filter_by(active=True)
    q = request.args.get("q", "").strip()[:100]
    if q:
        query = query.filter(
            db.or_(
                Product.name.contains(q, autoescape=True),
                Product.sku.contains(q, autoescape=True),
                Product.barcode.contains(q, autoescape=True),
            )
        )
    for key in ("category_id", "supplier_id"):
        if request.args.get(key):
            query = query.filter(getattr(Product, key) == integer(request.args[key], 1))
    status = request.args.get("status")
    if status == "low":
        query = query.filter(Product.stock > 0, Product.stock <= Product.minimum)
    if status == "out":
        query = query.filter(Product.stock == 0)
    if status == "in":
        query = query.filter(Product.stock > Product.minimum)
    return query


@catalog.get("/inventory")
@catalog.get("/products")
def products():
    from services.prices import (
        latest_changes,
        money,
    )

    inventory = request.path == "/inventory"
    page = (
        product_query()
        .order_by(Product.id)
        .paginate(
            page=max(1, request.args.get("page", 1, type=int)),
            per_page=int(g.settings["items_per_page"]),
            error_out=False,
        )
    )
    selected = (
        db.session.get(Product, request.args.get("selected", type=int))
        if request.args.get("selected")
        else (page.items[0] if page.items else None)
    )
    stock = stock_stats()
    attention = Product.query.filter(Product.active.is_(True), Product.stock <= Product.minimum)
    stock["products"] = (
        attention.filter(Product.stock > 0).order_by(Product.stock, Product.name).limit(8).all()
        + attention.filter(Product.stock == 0).order_by(Product.name).limit(8).all()
    )
    loc_rows = (
        db.session.query(
            db.func.coalesce(db.func.nullif(Product.location, ""), "Unassigned"),
            db.func.coalesce(db.func.sum(Product.stock * Product.cost), 0),
        )
        .filter(Product.active.is_(True))
        .group_by(Product.location)
        .all()
    )
    locations = {str(loc): int(val) for loc, val in loc_rows}
    categories = Category.query.order_by(Category.name).all()
    category_counts = dict(
        db.session.query(
            Product.category_id, db.func.count(Product.id)
        )
        .filter(Product.active.is_(True))
        .group_by(Product.category_id)
        .all()
    )
    cat_val_rows = dict(
        db.session.query(
            Product.category_id,
            db.func.coalesce(db.func.sum(Product.stock * Product.cost), 0),
        )
        .filter(Product.active.is_(True))
        .group_by(Product.category_id)
        .all()
    )
    chart = {
        "labels": [c.name for c in categories],
        "datasets": [
            {
                "label": "Stock value",
                "data": [
                    cat_val_rows.get(c.id, 0) / 100
                    for c in categories
                ],
                "backgroundColor": "#3985ff",
            }
        ],
    }
    return render_template(
        "inventory/index.html" if inventory else "products/index.html",
        title="Inventory" if inventory else "Products",
        page=page,
        selected=selected,
        stock=stock,
        locations=locations,
        categories=categories,
        category_counts=category_counts,
        suppliers=Supplier.query.filter_by(active=True).all(),
        chart=chart,
        movements=InventoryMovement.query.order_by(InventoryMovement.id.desc())
        .limit(4)
        .all(),
        price_changes=latest_changes([p.id for p in page.items]),
        price_money=money,
        archived_count=Product.query.filter_by(active=False).count(),
    )


@catalog.route("/products/new", methods=["GET", "POST"])
@catalog.route("/products/<int:pid>/edit", methods=["GET", "POST"])
def product_form(pid=None):
    product = db.get_or_404(Product, pid) if pid else None
    if request.method == "POST":
        p = product or Product(stock=0)
        p.name = required(request.form.get("name"), "Product name")
        p.sku = required(request.form.get("sku"), "SKU", 60)
        p.barcode = request.form.get("barcode", "").strip()[:80] or None
        p.brand = request.form.get("brand", "")[:80]
        p.category_id = integer(request.form.get("category_id"), 1)
        if not db.session.get(Category, p.category_id):
            raise ValueError("Choose a category.")
        p.supplier_id = (
            integer(request.form["supplier_id"], 1)
            if request.form.get("supplier_id")
            else None
        )
        if p.supplier_id and not db.session.get(Supplier, p.supplier_id):
            raise ValueError("Choose a supplier.")
        from services.permissions import require

        if product and (
            cents(request.form.get("price")) != p.price
            or cents(request.form.get("cost")) != p.cost
        ):
            require("products.price_change")
        p.price, p.cost = (
            cents(request.form.get("price")),
            cents(request.form.get("cost")),
        )
        min_val = request.form.get("minimum")
        p.minimum = (
            integer(min_val)
            if min_val not in (None, "")
            else integer(g.settings.get("low_stock_default", 5))
        )
        p.location = request.form.get("location", "")[:60]
        # Legacy single-image field (kept for backwards compat).
        uploaded = save_image(request.files.get("image"))
        if uploaded:
            p.image = uploaded
        db.session.add(p)
        db.session.flush()
        if product and request.form.get("current_stock") not in (None, ""):
            # Editable stock count: any change writes a ledger movement so the
            # audit trail stays complete. Same Product.stock column, no duplicate.
            new_stock = integer(request.form.get("current_stock"), 0)
            baseline = request.form.get("stock_baseline")
            baseline = integer(baseline, 0) if baseline not in (None, "") else p.stock
            if new_stock != baseline:
                if p.stock != baseline:
                    raise ValueError(
                        f"Stock changed to {p.stock} since this page was opened. Reload before editing the stock count."
                    )
                move(p, new_stock - p.stock, "Adjustment", "Manual Product Edit")
        # Multi-image gallery: new uploads submitted with the product form.
        # (Existing products are otherwise managed live via the image API.)
        from services.product_media import (
            store_upload,
            ordered_records,
            ensure_primary,
        )

        gallery_files = request.files.getlist("images") or request.files.getlist("gallery")
        if gallery_files and any(f and f.filename for f in gallery_files):
            if len([f for f in gallery_files if f and f.filename]) > 20:
                raise ValueError("Upload at most 20 images at a time.")
            existing_orders = [r.sort_order for r in ordered_records(p.id)]
            base = max(existing_orders) if existing_orders else -1
            primary_index = request.form.get("primary_index", "")
            try:
                primary_index = int(primary_index)
            except (TypeError, ValueError):
                primary_index = 0
            for offset, file in enumerate(
                [f for f in gallery_files if f and f.filename]
            ):
                record = store_upload(
                    file,
                    p.id,
                    sort_order=base + 1 + offset,
                    is_primary=False,
                )
                if not product and offset == primary_index:
                    record.is_primary = True
            ensure_primary(p.id)
        if not product:
            stock_val = request.form.get("stock")
            initial = integer(stock_val) if stock_val not in (None, "") else 0
            if initial:
                move(p, initial, "Opening stock", "Product creation")
        audit("Edit product" if product else "Add product", p.sku)
        db.session.commit()
        flash("Product saved.", "success")
        return redirect(url_for("catalog.products", selected=p.id))
    gallery = []
    last_movement = None
    if product:
        from services.product_media import (
            migrate_legacy,
            ordered_records,
            serialize_image,
        )

        if not ProductImage.query.filter_by(product_id=product.id).count():
            migrate_legacy(product)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        gallery = [serialize_image(r) for r in ordered_records(product.id)]
        last_movement = (
            InventoryMovement.query.filter_by(product_id=product.id)
            .order_by(InventoryMovement.id.desc())
            .first()
        )
    return render_template(
        "products/form.html",
        title="Edit Product" if product else "Add Product",
        product=product,
        categories=Category.query.all(),
        suppliers=Supplier.query.filter_by(active=True).all(),
        gallery=gallery,
        last_movement=last_movement,
    )


@catalog.post("/products/<int:pid>/delete")
def delete_product(pid):
    p = db.get_or_404(Product, pid)
    if p.stock:
        raise ValueError("Adjust stock to zero before deleting this product.")
    if db.session.scalar(
        db.select(PurchaseItem.id)
        .join(Purchase)
        .where(
            PurchaseItem.product_id == pid,
            Purchase.status.in_(["Pending", "Processing"]),
        )
    ):
        raise ValueError(
            "Receive or cancel pending orders before deleting this product."
        )
    p.active = False
    audit("Archive product", p.sku)
    db.session.commit()
    flash(
        "Product deleted from the catalog. Historical records are retained.", "success"
    )
    return redirect(url_for("catalog.products"))


@catalog.route("/inventory/adjust", methods=["GET", "POST"])
def adjust():
    from services.inventory import apply_inventory_adjustment, get_adjustment_page_data

    if request.method == "POST":
        with current_app.config["DB_LOCK"]:
            p, details, clamped = apply_inventory_adjustment(request.form, g.user)
        if clamped and "already zero" in details:
            flash(details, "info")
            return redirect("/inventory")
        flash("Stock updated.", "success")
        if request.form.get("save_and_new"):
            return redirect(f"/inventory/adjust?product_id={p.id}")
        return redirect("/inventory")

    selected_id = request.args.get("product_id", type=int)
    view_data = get_adjustment_page_data(selected_id, g.user, g.settings["currency"])
    return render_template(
        "inventory/adjust.html",
        title="Adjust Stock",
        **view_data,
    )


@catalog.get("/inventory/movements")
def movements():
    query = InventoryMovement.query
    if request.args.get("product_id"):
        query = query.filter_by(product_id=integer(request.args["product_id"], 1))
    page = query.order_by(InventoryMovement.id.desc()).paginate(
        page=max(1, request.args.get("page", 1, type=int)), per_page=30, error_out=False
    )
    return render_template(
        "inventory/movements.html", title="Stock Movement", page=page
    )


@catalog.route("/<kind>", methods=["GET"])
def contacts(kind):
    if kind not in ("customers", "suppliers", "categories"):
        abort(404)
    model = {"customers": Customer, "suppliers": Supplier, "categories": Category}[kind]
    query = model.query
    if kind != "categories":
        query = query.filter_by(active=True)
    if request.args.get("q"):
        query = query.filter(
            model.name.contains(request.args["q"][:100], autoescape=True)
        )
    page = query.order_by(model.name).paginate(
        page=max(1, request.args.get("page", 1, type=int)), per_page=20, error_out=False
    )
    edit = model.query.filter_by(id=request.args.get("edit", type=int))
    if kind != "categories":
        edit = edit.filter_by(active=True)  # a removed record cannot be edited back in
    return render_template(
        "contacts.html",
        title=kind.title(),
        kind=kind,
        page=page,
        edit=edit.first(),
    )


@catalog.post("/contacts/<kind>/save")
def save_contact(kind):
    if kind not in ("customers", "suppliers", "categories"):
        abort(404)

    model = {"customers": Customer, "suppliers": Supplier, "categories": Category}[kind]
    row = (
        db.get_or_404(model, integer(request.form["id"], 1))
        if request.form.get("id")
        else model()
    )
    row.name = required(request.form.get("name"), "Name", 100)
    if kind != "categories":
        row.phone = request.form.get("phone", "")[:40]
        row.email = request.form.get("email", "")[:120]
        row.address = request.form.get("address", "")[:300]
    db.session.add(row)
    audit("Save " + kind, row.name)
    db.session.commit()
    flash("Saved.", "success")
    return redirect(url_for("catalog.contacts", kind=kind))


@catalog.post("/api/suppliers")
def api_create_supplier():
    data = request.get_json(silent=True) or {}
    name = required(data.get("name"), "Supplier name", 100)
    supplier = Supplier(
        name=name,
        phone=(data.get("phone") or "")[:40],
        email=(data.get("email") or "")[:120],
        address=(data.get("address") or "")[:300],
    )
    db.session.add(supplier)
    audit("Create supplier", supplier.name)
    db.session.commit()
    return jsonify(supplier={"id": supplier.id, "name": supplier.name}), 201


@catalog.post("/contacts/<kind>/<int:pid>/delete")
def delete_contact(kind, pid):
    if kind not in ("customers", "suppliers", "categories"):
        abort(404)
    model = {"customers": Customer, "suppliers": Supplier, "categories": Category}[kind]
    row = db.get_or_404(model, pid)
    if kind == "categories":
        if Product.query.filter_by(category_id=pid).first():
            raise ValueError("This category is used by a product.")
        db.session.delete(row)
    else:
        row.active = False
    audit("Delete " + kind, row.name)
    db.session.commit()
    flash("Record removed.", "success")
    return redirect(url_for("catalog.contacts", kind=kind))


@catalog.get("/api/customers/<int:cid>/profile")
def customer_profile(cid):
    """Customer profile payload (same shape as the shipping variant)."""
    customer = db.get_or_404(Customer, cid)
    peer_orders = ShippingOrder.query.filter_by(customer_id=cid).all()
    delivered = sum(1 for o in peer_orders if o.status == "Delivered")
    return jsonify(
        profile={
            "name": customer.name,
            "phone": customer.phone or "",
            "email": customer.email or "",
            "address": customer.address or "",
            "active": bool(customer.active),
        },
        stats={
            "shipments": len(peer_orders),
            "delivered": delivered,
            "open": sum(
                1
                for o in peer_orders
                if o.status not in ("Delivered", "Returned", "Cancelled")
            ),
        },
    )


@catalog.get("/products/export/csv")
def export_products_csv():
    from services.product_import_export import generate_catalog_csv
    return generate_catalog_csv()


@catalog.post("/products/import/csv")
def import_products_csv():
    from services.product_import_export import process_catalog_import_csv

    if "file" not in request.files:
        flash("No file was uploaded.", "danger")
        return redirect(url_for("catalog.products"))

    file = request.files["file"]
    try:
        created, updated = process_catalog_import_csv(file)
        flash(f"CSV Import successful: {created} products created, {updated} updated.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Product CSV import failed")
        flash("Failed to import products. Check that SKUs and barcodes are unique, then try again.", "danger")

    return redirect(url_for("catalog.products"))


@catalog.post("/api/products/<int:pid>/adjust-price")
def adjust_price(pid):
    from services.permissions import require

    require("products.price_change")
    product = db.get_or_404(Product, pid)
    payload = request.get_json(silent=True) or request.form
    raw_price = payload.get("price")
    if raw_price is None or str(raw_price).strip() == "":
        return jsonify(error="Selling price is required."), 400
    try:
        new_price = cents(raw_price)
        if new_price < 0:
            raise ValueError()
    except Exception:
        return jsonify(error="Selling price must be a non-negative number."), 400

    old_price = product.price
    product.price = new_price

    raw_cost = payload.get("cost")
    if raw_cost is not None and str(raw_cost).strip() != "":
        try:
            new_cost = cents(raw_cost)
            if new_cost < 0:
                raise ValueError()
            product.cost = new_cost
        except Exception:
            return jsonify(error="Cost price must be a non-negative number."), 400

    audit("Adjust price", f"{product.sku}: {old_price} → {product.price}")
    db.session.commit()
    return jsonify(
        success=True,
        product_id=product.id,
        price=product.price,
        cost=product.cost,
    )
