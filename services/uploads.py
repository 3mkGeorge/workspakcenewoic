from uuid import uuid4
from PIL import Image, UnidentifiedImageError
from flask import current_app


def save_image(file):
    if not file or not file.filename:
        return None
    try:
        picture = Image.open(file.stream)
        if picture.width * picture.height > 20_000_000:
            raise ValueError("Choose an image smaller than 20 megapixels.")
        picture.load()
        picture.thumbnail((1200, 1200))
        name = uuid4().hex + ".png"
        target = current_app.config["ROOT"] / "static/uploads" / name
        pending = target.with_suffix(".uploading")
        try:
            picture.convert("RGBA").save(pending, "PNG")
            pending.replace(target)
        finally:
            pending.unlink(missing_ok=True)
        return name
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        import errno
        if getattr(exc, "errno", None) == errno.ENOSPC or "space" in str(exc).lower() or "disk full" in str(exc).lower():
            raise ValueError("Insufficient disk space to save image.") from exc
        raise ValueError("Upload a valid PNG, JPG, or WebP image.") from exc
