"""Multi-image product gallery storage.

Files live under ``static/uploads/products/<product_id>/`` with unique
hex filenames (never overwritten). Thumbnails live in ``thumbs/`` and are
used in tables; full-size images load only in gallery modals.
"""

from pathlib import Path
from uuid import uuid4

from flask import current_app, url_for
from PIL import Image, UnidentifiedImageError

from models import db, Product, ProductImage, now

ALLOWED = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
MAX_PIXELS = 20_000_000
FULL_SIZE = (1600, 1600)
THUMB_SIZE = (320, 320)


def _root():
    return current_app.config["ROOT"]


def product_dir(product_id):
    path = _root() / "static" / "uploads" / "products" / str(int(product_id))
    (path / "thumbs").mkdir(parents=True, exist_ok=True)
    return path


def _extension(filename):
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix not in ALLOWED:
        raise ValueError("Upload JPG, PNG, or WebP images only.")
    return suffix


def _unique_name(suffix):
    return uuid4().hex + suffix


def image_urls(record):
    """Return (full_url, thumb_url) for a ProductImage record."""
    if (record.file_path or "").startswith("legacy:"):
        url = url_for("static", filename="uploads/" + record.file_name)
        return url, url
    base = f"uploads/products/{record.product_id}/{record.file_name}"
    thumb = f"uploads/products/{record.product_id}/thumbs/{record.file_name}"
    root = _root()
    full_path = root / "static" / base
    thumb_path = root / "static" / thumb
    full_url = url_for("static", filename=base) if full_path.exists() else ""
    if thumb_path.exists():
        thumb_url = url_for("static", filename=thumb)
    else:
        thumb_url = full_url
    return full_url, thumb_url


def legacy_url(product):
    if getattr(product, "image", None):
        return url_for("static", filename="uploads/" + product.image)
    return ""


def primary_urls(product):
    """Primary image (full, thumb) with legacy fallback."""
    primary = (product.primary_image if hasattr(product, "primary_image") else None)
    if primary is not None:
        full, thumb = image_urls(primary)
        if full:
            return full, thumb or full
    if getattr(product, "image", None):
        url = legacy_url(product)
        if url:
            return url, url
    return "", ""


def serialize_image(record):
    full, thumb = image_urls(record)
    return {
        "id": record.id,
        "product_id": record.product_id,
        "file_name": record.file_name,
        "file_path": record.file_path,
        "url": full,
        "thumb_url": thumb or full,
        "is_primary": bool(record.is_primary),
        "sort_order": record.sort_order,
    }


def ordered_records(product_id):
    return (
        ProductImage.query.filter_by(product_id=int(product_id))
        .order_by(ProductImage.sort_order, ProductImage.id)
        .all()
    )


def _save_files(picture, directory, name):
    suffix = Path(name).suffix.lower()
    fmt = ALLOWED[suffix]
    full_target = directory / name
    thumb_target = directory / "thumbs" / name
    # Full size (bounded, never overwrites: name is unique hex).
    full = picture.copy()
    full.thumbnail(FULL_SIZE)
    pending = full_target.with_suffix(full_target.suffix + ".uploading")
    try:
        if fmt == "JPEG":
            full.convert("RGB").save(pending, fmt, quality=88)
        elif fmt == "WEBP":
            full.save(pending, fmt, quality=88, method=4)
        else:
            full.convert("RGBA").save(pending, fmt)
        pending.replace(full_target)
    finally:
        pending.unlink(missing_ok=True)
    # Thumbnail for tables.
    thumb = picture.copy()
    thumb.thumbnail(THUMB_SIZE)
    tpending = thumb_target.with_suffix(thumb_target.suffix + ".uploading")
    try:
        if fmt == "JPEG":
            thumb.convert("RGB").save(tpending, fmt, quality=82)
        elif fmt == "WEBP":
            thumb.save(tpending, fmt, quality=80, method=4)
        else:
            thumb.convert("RGBA").save(tpending, fmt)
        tpending.replace(thumb_target)
    finally:
        tpending.unlink(missing_ok=True)
    finally_cleanup = None
    return full_target


def store_upload(file_storage, product_id, sort_order=0, is_primary=False):
    if not file_storage or not file_storage.filename:
        raise ValueError("Choose an image to upload.")
    suffix = _extension(file_storage.filename)
    try:
        picture = Image.open(file_storage.stream)
        if picture.width * picture.height > MAX_PIXELS:
            raise ValueError("Choose an image smaller than 20 megapixels.")
        picture.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("Upload a valid PNG, JPG, or WebP image.")
    directory = product_dir(product_id)
    name = _unique_name(suffix)
    try:
        _save_files(picture, directory, name)
    except OSError as exc:
        import errno
        if getattr(exc, "errno", None) == errno.ENOSPC or "space" in str(exc).lower() or "disk full" in str(exc).lower():
            raise ValueError("Insufficient disk space to save product image.") from exc
        raise
    record = ProductImage(
        product_id=int(product_id),
        file_path=f"products/{int(product_id)}/{name}",
        file_name=name,
        is_primary=bool(is_primary),
        sort_order=int(sort_order),
        created_at=now(),
    )
    db.session.add(record)
    db.session.flush()
    return record


def sync_primary(product):
    """Keep legacy Product.image pointing at the primary gallery image name."""
    primary = product.primary_image
    if primary is not None:
        # Legacy column stores bare filenames; gallery files live in subfolders,
        # so keep a synthetic pointer the macro understands via primary_urls().
        # Preserve the legacy file itself for old backups.
        pass
    return primary


def ensure_primary(product_id):
    records = ordered_records(product_id)
    if not records:
        return None
    if not any(r.is_primary for r in records):
        records[0].is_primary = True
        db.session.flush()
        return records[0]
    return next(r for r in records if r.is_primary)


def set_primary(product_id, image_id):
    records = ordered_records(product_id)
    found = None
    for record in records:
        record.is_primary = record.id == int(image_id)
        if record.is_primary:
            found = record
    if found is None:
        raise ValueError("Image not found for this product.")
    db.session.flush()
    return found


def reorder(product_id, ids):
    records = {r.id: r for r in ordered_records(product_id)}
    order = [int(i) for i in (ids or [])]
    if set(order) != set(records):
        raise ValueError("Reorder list must include every image exactly once.")
    for position, image_id in enumerate(order):
        records[image_id].sort_order = position
    db.session.flush()
    return ordered_records(product_id)


def delete_image(product_id, image_id):
    record = ProductImage.query.filter_by(
        id=int(image_id), product_id=int(product_id)
    ).first()
    if record is None:
        raise ValueError("Image not found for this product.")
    root = _root() / "static" / "uploads"
    for candidate in (
        root / "products" / str(int(product_id)) / record.file_name,
        root / "products" / str(int(product_id)) / "thumbs" / record.file_name,
    ):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass
    was_primary = bool(record.is_primary)
    db.session.delete(record)
    db.session.flush()
    if was_primary:
        ensure_primary(product_id)
    return True


def delete_product_files(product):
    """Remove every image file belonging to a product being hard-deleted."""
    from pathlib import Path

    from flask import current_app as capp

    uploads = Path(capp.config["ROOT"]) / "static" / "uploads"
    gallery = uploads / "products" / str(product.id)
    if gallery.is_dir():
        for child in sorted(gallery.rglob("*")):
            try:
                if child.is_file() or child.is_symlink():
                    child.unlink()
            except OSError:
                pass
        for child in (gallery / "thumbs", gallery):
            try:
                child.rmdir()
            except OSError:
                pass
    if getattr(product, "image", None):
        still_used = (
            db.session.query(Product.id)
            .filter(Product.image == product.image, Product.id != product.id)
            .first()
            is not None
        )
        if not still_used:
            try:
                (uploads / product.image).unlink(missing_ok=True)
            except OSError:
                pass


def replace_image(product_id, image_id, file_storage):
    record = ProductImage.query.filter_by(
        id=int(image_id), product_id=int(product_id)
    ).first()
    if record is None:
        raise ValueError("Image not found for this product.")
    if not file_storage or not file_storage.filename:
        raise ValueError("Choose a replacement image.")
    suffix = _extension(file_storage.filename)
    try:
        picture = Image.open(file_storage.stream)
        if picture.width * picture.height > MAX_PIXELS:
            raise ValueError("Choose an image smaller than 20 megapixels.")
        picture.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("Upload a valid PNG, JPG, or WebP image.")
    directory = product_dir(product_id)
    old_name = record.file_name
    new_name = _unique_name(suffix)
    _save_files(picture, directory, new_name)
    record.file_name = new_name
    record.file_path = f"products/{int(product_id)}/{new_name}"
    record.created_at = now()
    db.session.flush()
    # Remove old files only after the new ones are safely stored.
    root = _root() / "static" / "uploads"
    for candidate in (
        root / "products" / str(int(product_id)) / old_name,
        root / "products" / str(int(product_id)) / "thumbs" / old_name,
    ):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass
    return record


def migrate_legacy(product):
    """Backfill one gallery record from the legacy single-image column."""
    if not getattr(product, "image", None):
        return None
    if ProductImage.query.filter_by(product_id=product.id).count():
        return None
    legacy = _root() / "static" / "uploads" / product.image
    if not legacy.exists():
        return None
    record = ProductImage(
        product_id=product.id,
        file_path=f"legacy:{product.image}",
        file_name=product.image,
        is_primary=True,
        sort_order=0,
        created_at=now(),
    )
    db.session.add(record)
    db.session.flush()
    return record


def migrate_all_legacy():
    for product in Product.query.all():
        try:
            migrate_legacy(product)
        except Exception:
            db.session.rollback()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
