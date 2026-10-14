"""StorePro -> Next Chip website catalog publisher (Stage 1: catalog only).

StorePro pushes an HMAC-signed snapshot of the products an operator has
published (web_listings.published) to the Next Chip server over outbound
HTTPS. The website never connects to StorePro, and StorePro never exposes its
local server. Only public fields are exported: SKU, web name/description,
category, brand, selling price (piastres, EGP), an availability status with a
quantity capped at the per-order limit, and public product photos. Cost,
supplier, barcode, location, minimum-stock thresholds and exact stock levels
never leave the store.

Configuration (environment variables, or instance/web-sync.env; see .env.example):
    NEXT_CHIP_SYNC_ENABLED   true/false master switch (default false)
    NEXT_CHIP_SYNC_URL       website origin, e.g. https://shop.example.com
    NEXT_CHIP_SYNC_SECRET    shared HMAC secret, at least 32 characters
    NEXT_CHIP_SYNC_INTERVAL_MINUTES, NEXT_CHIP_SYNC_MAX_PER_ORDER, NEXT_CHIP_SYNC_TIMEOUT_SECONDS
"""

import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import ssl
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app
from PIL import Image, UnidentifiedImageError

from models import db, Product, WebListing
from services.web_listings import ineligibility

log = logging.getLogger("storepro.web_sync")

SCHEMA_VERSION = 1
SIGNATURE_PREFIX = "NEXTCHIP-SYNC-V1"
MIN_SECRET_LENGTH = 32
MAX_IMAGES = 8
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PRICE = 1_000_000_000  # piastres; mirrors the website's validation ceiling
RETRY_STATUSES = {429, 500, 502, 503, 504}
ATTEMPTS = 3  # network errors and RETRY_STATUSES are retried after 2 s and 4 s
ENDPOINTS = {
    "snapshot": "/api/storepro/catalog-sync",
    "media_check": "/api/storepro/media/check",
    "media": "/api/storepro/media/",
    "status": "/api/storepro/status",
}
IMAGE_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_RUN_LOCK = threading.Lock()
_SCHEDULER_STARTED = False


class TransientError(Exception):
    """Network-level failure worth retrying (timeouts, refused connections, TLS)."""


@dataclass
class SyncConfig:
    enabled: bool = False
    url: str = ""
    secret: str = field(default="", repr=False)
    interval_minutes: int = 15
    max_per_order: int = 5
    timeout_seconds: int = 20
    problems: list = field(default_factory=list)

    @property
    def configured(self):
        return bool(self.url and self.secret) and not self.problems

    def public(self):
        """Safe to display: never includes the secret."""
        return {
            "enabled": self.enabled,
            "url": self.url,
            "secret_configured": bool(self.secret),
            "interval_minutes": self.interval_minutes,
            "max_per_order": self.max_per_order,
            "problems": list(self.problems),
        }


def _root():
    return Path(current_app.config["ROOT"])


def _env_file_values(path):
    values = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = re.sub(r"\s+#.*$", "", value.strip())  # allow "KEY=value   # comment"
            values[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return values


def _int(value, default, low, high):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def load_config(root=None, environ=None):
    """Environment variables win over instance/web-sync.env (which stays out of Git and backups)."""
    root = Path(root) if root else _root()
    values = _env_file_values(root / "instance" / "web-sync.env")
    values.update({k: v for k, v in (environ if environ is not None else os.environ).items() if k.startswith("NEXT_CHIP_SYNC_")})
    cfg = SyncConfig(
        enabled=str(values.get("NEXT_CHIP_SYNC_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on"),
        secret=str(values.get("NEXT_CHIP_SYNC_SECRET", "")).strip(),
        interval_minutes=_int(values.get("NEXT_CHIP_SYNC_INTERVAL_MINUTES"), 15, 5, 1440),
        max_per_order=_int(values.get("NEXT_CHIP_SYNC_MAX_PER_ORDER"), 5, 1, 99),
        timeout_seconds=_int(values.get("NEXT_CHIP_SYNC_TIMEOUT_SECONDS"), 20, 5, 120),
    )
    raw_url = str(values.get("NEXT_CHIP_SYNC_URL", "")).strip()
    if raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if parsed.scheme == "https" or (parsed.scheme == "http" and local):
            if parsed.query or parsed.fragment or parsed.path not in ("", "/") or parsed.username or parsed.password:
                cfg.problems.append("NEXT_CHIP_SYNC_URL must be the website origin only, e.g. https://shop.example.com")
            else:
                cfg.url = f"{parsed.scheme}://{parsed.netloc}"
        else:
            cfg.problems.append("NEXT_CHIP_SYNC_URL must use https:// (http:// is allowed only for localhost testing)")
    if cfg.secret and len(cfg.secret) < MIN_SECRET_LENGTH:
        cfg.problems.append(f"NEXT_CHIP_SYNC_SECRET must be at least {MIN_SECRET_LENGTH} characters")
    return cfg


# ---------------------------------------------------------------- state


def _state_path(root):
    return Path(root) / "instance" / "web_sync_state.json"


def load_state(root=None):
    root = Path(root) if root else _root()
    try:
        data = json.loads(_state_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _save_state(root, state):
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _iso(dt=None):
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------- snapshot

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(text, limit, multiline=False):
    text = unicodedata.normalize("NFC", str(text or ""))
    text = _CONTROL.sub("", text) if multiline else re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return text.strip()[:limit]


def slugify(text):
    ascii_text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:90].strip("-")


def availability(product, max_per_order):
    """Public status from StorePro's own rule (Product.status); quantity is capped by the per-order limit."""
    stock = max(0, int(product.stock or 0))
    if stock == 0:
        return "out_of_stock", 0
    status = "low_stock" if stock <= int(product.minimum or 0) else "in_stock"
    return status, min(stock, max_per_order)


def _image_files(root, product):
    """Ordered gallery files (primary first), with the legacy single image as fallback."""
    files = []
    ordered = product.ordered_images
    primary = product.primary_image
    if primary is not None:
        ordered = [primary] + [i for i in ordered if i.id != primary.id]
    for record in ordered:
        if (record.file_path or "").startswith("legacy:"):
            files.append(root / "static" / "uploads" / record.file_name)
        else:
            files.append(root / "static" / "uploads" / "products" / str(product.id) / record.file_name)
    if not files and product.image:
        files.append(root / "static" / "uploads" / product.image)
    return files[:MAX_IMAGES]


def _read_image(path):
    """Return (bytes, content_type, width, height) or raise ValueError with a reason."""
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise ValueError("file is missing")
    if resolved.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("file is larger than 5 MB")
    data = resolved.read_bytes()
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt, (width, height) = img.format, img.size
    except (UnidentifiedImageError, OSError):
        raise ValueError("file is not a readable image")
    if fmt not in IMAGE_TYPES:
        raise ValueError(f"unsupported format {fmt}")
    return data, IMAGE_TYPES[fmt], width, height


def build_snapshot(cfg, root=None, now=None):
    """Read published listings and return (snapshot, media, warnings). Read-only."""
    root = Path(root) if root else _root()
    now = now or datetime.now(timezone.utc)
    warnings = []
    media = {}
    categories, brands, products = {}, {}, []
    rows = (
        db.session.query(WebListing, Product)
        .join(Product, Product.id == WebListing.product_id)
        .filter(WebListing.published.is_(True))
        .order_by(Product.id)
        .all()
    )
    for listing, product in rows:
        sku = _clean(product.sku, 60)
        reason = ineligibility(product)
        if not reason and int(product.price) > MAX_PRICE:
            reason = "Price is above the website limit"
        if reason:
            warnings.append(f"{sku or product.id}: not published on the website ({reason[0].lower() + reason[1:]}).")
            continue
        name_en = _clean(listing.name_en, 160) or _clean(product.name, 160)
        name_ar = _clean(listing.name_ar, 160) or name_en
        max_po = listing.max_per_order or cfg.max_per_order
        status, orderable = availability(product, max_po)

        category = product.category
        cid = f"spc-{category.id}"
        if cid not in categories:
            cname = _clean(category.name, 100) or f"Category {category.id}"
            cdesc = _clean(category.description, 500, multiline=True)
            categories[cid] = {
                "id": cid,
                "slug": f"{slugify(cname) or 'category'}-{category.id}",
                "name": {"en": cname, "ar": cname},
                "description": {"en": cdesc, "ar": cdesc},
                "icon": category.icon if re.fullmatch(r"[a-z0-9-]{0,40}", category.icon or "") else "",
                "sortOrder": 0,
            }
        brand_name = _clean(product.brand, 80)
        bid = None
        if brand_name:
            bslug = slugify(brand_name) or "brand-" + hashlib.sha256(brand_name.encode()).hexdigest()[:10]
            bid = f"spb-{bslug}"[:64].rstrip("-")
            brands.setdefault(bid, {"id": bid, "slug": bslug, "name": brand_name})

        images = []
        for path in _image_files(root, product):
            try:
                data, ctype, width, height = _read_image(path)
            except ValueError as exc:
                warnings.append(f"{sku}: image {path.name} skipped ({exc}).")
                continue
            digest = hashlib.sha256(data).hexdigest()
            media[digest] = {"hash": digest, "contentType": ctype, "bytes": data}
            if all(i["hash"] != digest for i in images):
                images.append({"hash": digest, "contentType": ctype, "width": width, "height": height})
        if not images:
            warnings.append(f"{sku}: no usable image; the website shows a placeholder.")

        updated = max(d for d in (product.updated_at, listing.updated_at, product.created_at) if d)
        products.append(
            {
                "id": f"sp-{product.id}",
                "sku": sku,
                "slug": f"{slugify(name_en) or 'product'}-{product.id}",
                "name": {"en": name_en, "ar": name_ar},
                "description": {
                    "en": _clean(listing.description_en, 4000, multiline=True),
                    "ar": _clean(listing.description_ar, 4000, multiline=True),
                },
                "categoryId": cid,
                "brandId": bid,
                "price": int(product.price),
                "compareAt": None,
                "saleEndsAt": None,
                "availability": status,
                "orderableQuantity": orderable,
                "maxPerOrder": max_po,
                "images": images,
                "published": True,
                "createdAt": _iso(product.created_at),
                "updatedAt": _iso(updated),
            }
        )
    # Two published products must not share a SKU case-insensitively on the website;
    # keep the first and report the other instead of failing the whole batch.
    seen, unique_products = set(), []
    for p in products:
        key = p["sku"].lower()
        if key in seen:
            warnings.append(f"{p['sku']}: not published (SKU differs from another product only by letter case).")
            continue
        seen.add(key)
        unique_products.append(p)
    products = unique_products
    used_categories = {p["categoryId"] for p in products}
    used_brands = {p["brandId"] for p in products if p["brandId"]}
    categories = {k: v for k, v in categories.items() if k in used_categories}
    brands = {k: v for k, v in brands.items() if k in used_brands}
    for i, c in enumerate(sorted(categories.values(), key=lambda c: c["name"]["en"].lower())):
        c["sortOrder"] = i
    content = {
        "categories": sorted(categories.values(), key=lambda c: c["id"]),
        "brands": sorted(brands.values(), key=lambda b: b["id"]),
        "products": products,
    }
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    sequence = int(now.timestamp() * 1000)
    snapshot = {
        "schemaVersion": SCHEMA_VERSION,
        "source": "storepro",
        "snapshot": {
            "id": f"sp-{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z-{digest[:12]}",
            "sequence": sequence,
            "generatedAt": _iso(now),
            "complete": True,
        },
        "currency": "EGP",
        **content,
    }
    return snapshot, list(media.values()), warnings


# ---------------------------------------------------------------- transport


def sign(secret, method, path, timestamp, nonce, body):
    canonical = "\n".join(
        [SIGNATURE_PREFIX, method.upper(), path, timestamp, nonce, hashlib.sha256(body).hexdigest()]
    )
    return "v1=" + hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A redirect could send the signed payload somewhere else; treat it as an error.
    def redirect_request(self, *args, **kwargs):
        return None


def _opener():
    return urllib.request.build_opener(
        _NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )


def _send(cfg, method, path, body=b"", content_type="application/json"):
    """One signed request. Returns (status, parsed_json_or_None)."""
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    headers = {
        "X-NextChip-Timestamp": timestamp,
        "X-NextChip-Nonce": nonce,
        "X-NextChip-Signature": sign(cfg.secret, method, path, timestamp, nonce, body),
        "User-Agent": "StorePro-WebCatalogSync/1",
        "Accept": "application/json",
    }
    if method != "GET":
        headers["Content-Type"] = content_type
    request = urllib.request.Request(cfg.url + path, data=body if method != "GET" else None, method=method, headers=headers)
    try:
        with _opener().open(request, timeout=cfg.timeout_seconds) as response:
            status, raw = response.status, response.read(1_000_000)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(1_000_000) if exc.fp else b""
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TransientError(f"Website unreachable ({type(reason).__name__}: {str(reason)[:160]})") from None
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        return status, None


def _send_with_retries(cfg, method, path, body=b"", content_type="application/json", attempts=ATTEMPTS, delay=2.0, sleep=time.sleep):
    """Retry network failures and 429/5xx with exponential backoff; a fresh nonce/timestamp each time."""
    last_error = None
    for attempt in range(attempts):
        try:
            status, payload = _send(cfg, method, path, body, content_type)
            if status not in RETRY_STATUSES:
                return status, payload
            last_error = TransientError(_describe_rejection(status, payload))
        except TransientError as exc:
            last_error = exc
        if attempt < attempts - 1:
            sleep(delay * (2**attempt))
    raise last_error


# ---------------------------------------------------------------- run


def _describe_rejection(status, payload):
    payload = payload if isinstance(payload, dict) else {}
    code = payload.get("error") or "error"
    detail = payload.get("message") or ""
    issues = payload.get("issues") or []
    if issues and isinstance(issues, list) and isinstance(issues[0], dict):
        detail = f"{len(issues)} problem(s); first: {issues[0].get('path', '')} {issues[0].get('message', '')}"
    return f"Website rejected the request (HTTP {status}, {code}){': ' + str(detail)[:300] if detail else ''}"


def run_sync(trigger="manual", dry_run=False, root=None, cfg=None, sleep=time.sleep):
    """Build and publish one complete snapshot. Returns a result dict; never raises for sync errors."""
    root = Path(root) if root else _root()
    cfg = cfg or load_config(root)
    if not _RUN_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "A website sync is already running."}
    try:
        if dry_run:
            snapshot, media, warnings = build_snapshot(cfg, root)
            return {
                "ok": True,
                "dry_run": True,
                "products": len(snapshot["products"]),
                "categories": len(snapshot["categories"]),
                "brands": len(snapshot["brands"]),
                "images": len(media),
                "snapshot_id": snapshot["snapshot"]["id"],
                "warnings": warnings,
            }
        if not cfg.enabled:
            return {"ok": False, "skipped": True, "error": "Website sync is disabled (NEXT_CHIP_SYNC_ENABLED is not true)."}
        if not cfg.configured:
            problems = cfg.problems or ["NEXT_CHIP_SYNC_URL and NEXT_CHIP_SYNC_SECRET must both be set."]
            return _finish(root, trigger, ok=False, error="Configuration: " + "; ".join(problems))

        snapshot, media, warnings = build_snapshot(cfg, root)
        body = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            uploaded = 0
            hashes = [m["hash"] for m in media]
            missing = set()
            for i in range(0, len(hashes), 1000):
                status, payload = _send_with_retries(
                    cfg, "POST", ENDPOINTS["media_check"], json.dumps({"hashes": hashes[i : i + 1000]}).encode(), sleep=sleep
                )
                if status != 200 or not isinstance(payload, dict):
                    return _finish(root, trigger, ok=False, error=_describe_rejection(status, payload), warnings=warnings)
                missing.update(payload.get("missing") or [])
            for item in media:
                if item["hash"] not in missing:
                    continue
                status, payload = _send_with_retries(
                    cfg, "PUT", ENDPOINTS["media"] + item["hash"], item["bytes"], item["contentType"], sleep=sleep
                )
                if status in (200, 201):
                    uploaded += 1
                else:
                    warnings.append(f"Image {item['hash'][:12]}… was not accepted ({_describe_rejection(status, payload)}).")
            status, payload = _send_with_retries(cfg, "POST", ENDPOINTS["snapshot"], body, sleep=sleep)
        except TransientError as exc:
            return _finish(root, trigger, ok=False, error=f"Gave up after {ATTEMPTS} attempts. {exc}", warnings=warnings, snapshot=snapshot)
        if status != 200 or not isinstance(payload, dict):
            return _finish(root, trigger, ok=False, error=_describe_rejection(status, payload), warnings=warnings, snapshot=snapshot)
        if payload.get("missingMedia"):
            warnings.append(f"{len(payload['missingMedia'])} image(s) are still missing on the website; they will be retried next sync.")
        return _finish(
            root,
            trigger,
            ok=True,
            snapshot=snapshot,
            warnings=warnings,
            website=payload,
            uploaded=uploaded,
        )
    except Exception as exc:  # unexpected local error: report without payload details
        log.exception("Website catalog sync failed")
        return _finish(root, trigger, ok=False, error=f"Unexpected error while syncing: {type(exc).__name__}")
    finally:
        _RUN_LOCK.release()


def _finish(root, trigger, ok, error=None, warnings=None, snapshot=None, website=None, uploaded=0):
    state = load_state(root)
    now = _iso()
    state["last_attempt_at"] = now
    state["last_trigger"] = trigger
    state["last_warnings"] = (warnings or [])[:25]
    if ok:
        state.update(
            {
                "last_success_at": now,
                "last_result": website.get("status"),
                "last_snapshot_id": website.get("snapshotId"),
                "last_sequence": snapshot["snapshot"]["sequence"],
                "last_product_count": website.get("publishedProducts"),
                "last_unpublished": website.get("unpublishedProducts", 0),
                "last_complete": bool(snapshot["snapshot"]["complete"]),
                "last_images_uploaded": uploaded,
                "last_ok": True,
            }
        )
    else:
        state.update({"last_failure_at": now, "last_error": (error or "")[:500], "last_ok": False})
    _save_state(root, state)
    level = logging.INFO if ok else logging.WARNING
    log.log(level, "Website catalog sync (%s): %s", trigger, "ok" if ok else state["last_error"])
    result = {"ok": ok, "state": state}
    if error:
        result["error"] = error
    return result


def website_status(cfg):
    """Ask the website what it last applied (signed GET). Returns (dict|None, error|None)."""
    if not cfg.configured:
        return None, "not configured"
    try:
        status, payload = _send(cfg, "GET", ENDPOINTS["status"])
    except TransientError as exc:
        return None, str(exc)
    if status != 200 or not isinstance(payload, dict):
        return None, _describe_rejection(status, payload)
    return payload, None


def start_web_sync(app):
    """Scheduled publisher thread. Started only by the locked server process (app.py), so exactly one runs."""
    global _SCHEDULER_STARTED
    if _SCHEDULER_STARTED or app.config.get("TESTING"):
        return None
    _SCHEDULER_STARTED = True
    from services.job_monitor import job_monitor

    job_monitor.register("web_catalog_sync", "Next Chip website catalog publisher", "Scheduled (when enabled)")

    def loop():
        time.sleep(60)  # let the server finish starting
        while True:
            with app.app_context():
                cfg = load_config(app.config["ROOT"])
                if cfg.enabled:
                    try:
                        with job_monitor.track("web_catalog_sync", "Scheduled website sync"):
                            result = run_sync("scheduled", root=app.config["ROOT"], cfg=cfg)
                            if not result.get("ok") and not result.get("skipped"):
                                raise RuntimeError(result.get("error", "sync failed"))
                    except Exception:
                        pass  # already recorded in web_sync_state.json and the job registry
                    finally:
                        db.session.remove()
                interval = cfg.interval_minutes
            time.sleep(interval * 60)

    thread = threading.Thread(target=loop, name="web-catalog-sync", daemon=True)
    thread.start()
    return thread
