from flask import Blueprint, jsonify, request, g
from models import db, Product, ProductImage
from services.core import audit
from services.permissions import require

product_media = Blueprint("product_media", __name__)


def _payload_product(pid):
    product = db.get_or_404(Product, int(pid))
    return product


@product_media.get("/api/products/<int:pid>/images")
def list_images(pid):
    from services.product_media import ordered_records, serialize_image

    product = _payload_product(pid)
    return jsonify(
        product_id=product.id,
        images=[serialize_image(r) for r in ordered_records(product.id)],
    )


@product_media.get("/api/products/<int:pid>/preview")
def preview(pid):
    from datetime import timedelta, timezone
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from services.product_media import ordered_records, serialize_image, primary_urls

    def cairo_date(value):
        # Same rules as the `date` template filter in app.py.
        if not value:
            return "—"
        try:
            value = value.replace(tzinfo=timezone.utc).astimezone(
                ZoneInfo("Africa/Cairo")
            )
        except ZoneInfoNotFoundError:
            value = value + timedelta(hours=3)
        fmt = "%d/%m/%Y" if g.settings["date_format"] == "DD/MM/YYYY" else "%Y-%m-%d"
        return value.strftime(fmt)

    product = _payload_product(pid)
    full_image, thumb_image = primary_urls(product)
    return jsonify(
        id=product.id,
        name=product.name,
        sku=product.sku,
        category=product.category.name if product.category else "",
        brand=product.brand or "",
        barcode=product.barcode or "",
        cost=product.cost,
        price=product.price,
        stock=product.stock,
        minimum=product.minimum,
        supplier=product.supplier.name if product.supplier else "",
        location=product.location or "",
        created_at=cairo_date(product.created_at),
        updated_at=cairo_date(product.updated_at),
        status=product.status,
        currency=g.settings["currency"],
        full_image=full_image or "",
        thumb_image=thumb_image or "",
        images=[serialize_image(r) for r in ordered_records(product.id)],
    )


@product_media.post("/api/products/<int:pid>/images")
def upload(pid):
    from services.product_media import (
        store_upload,
        ordered_records,
        serialize_image,
        ensure_primary,
    )

    require("products.edit")
    product = _payload_product(pid)
    files = request.files.getlist("images") or request.files.getlist("files")
    if not files:
        single = request.files.get("image")
        files = [single] if single else []
    if not files:
        raise ValueError("Choose at least one JPG, PNG, or WebP image.")
    if len(files) > 20:
        raise ValueError("Upload at most 20 images at a time.")
    existing = ProductImage.query.filter_by(product_id=product.id).count()
    base_order = max(
        [r.sort_order for r in ordered_records(product.id)] or [-1]
    )
    created = []
    for offset, file in enumerate(files):
        record = store_upload(
            file,
            product.id,
            sort_order=base_order + 1 + offset,
            is_primary=False,
        )
        created.append(record)
    ensure_primary(product.id)
    audit("Add product images", f"{product.sku}: {len(created)} image(s)")
    db.session.commit()
    _ = existing
    return jsonify(
        product_id=product.id,
        images=[serialize_image(r) for r in ordered_records(product.id)],
        added=[r.id for r in created],
    )


@product_media.post("/api/products/<int:pid>/images/reorder")
def reorder(pid):
    from services.product_media import reorder as do_reorder, ordered_records, serialize_image

    require("products.edit")
    product = _payload_product(pid)
    data = request.get_json(silent=True) or {}
    order = data.get("order") or data.get("ids") or []
    rows = do_reorder(product.id, order)
    audit("Reorder product images", product.sku)
    db.session.commit()
    return jsonify(
        product_id=product.id, images=[serialize_image(r) for r in rows]
    )


@product_media.post("/api/products/<int:pid>/images/<int:image_id>/primary")
def make_primary(pid, image_id):
    from services.product_media import set_primary, ordered_records, serialize_image

    require("products.edit")
    product = _payload_product(pid)
    set_primary(product.id, image_id)
    audit("Set primary product image", f"{product.sku}: #{image_id}")
    db.session.commit()
    return jsonify(
        product_id=product.id,
        images=[serialize_image(r) for r in ordered_records(product.id)],
    )


@product_media.post("/api/products/<int:pid>/images/<int:image_id>/delete")
@product_media.delete("/api/products/<int:pid>/images/<int:image_id>")
def delete(pid, image_id):
    from services.product_media import delete_image, ordered_records, serialize_image

    require("products.edit")
    product = _payload_product(pid)
    delete_image(product.id, image_id)
    audit("Delete product image", f"{product.sku}: #{image_id}")
    db.session.commit()
    return jsonify(
        product_id=product.id,
        images=[serialize_image(r) for r in ordered_records(product.id)],
    )


@product_media.post("/api/products/<int:pid>/images/<int:image_id>/replace")
def replace(pid, image_id):
    from services.product_media import replace_image, ordered_records, serialize_image

    require("products.edit")
    product = _payload_product(pid)
    file = request.files.get("image") or request.files.get("file")
    record = replace_image(product.id, image_id, file)
    audit("Replace product image", f"{product.sku}: #{record.id}")
    db.session.commit()
    return jsonify(
        product_id=product.id,
        images=[serialize_image(r) for r in ordered_records(product.id)],
    )
