"""Online SQLite snapshots, independently verified replicas, and bounded scheduling.

The single worker coalesces committed live changes. Compression, hashing and disk
copies never acquire the request lock. Restore exclusively locks the final swap.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import current_app, has_app_context
from sqlalchemy import event
from sqlalchemy.orm import Session

from models import db, BackupLog, User, AuditLog
from services.core import DEFAULTS, settings

FREQUENCIES = {
    "Every 15 Minutes": 900,
    "Every 30 Minutes": 1800,
    "Every Hour": 3600,
    "Every 6 Hours": 21600,
    "Daily": 86400,
    "Weekly": 604800,
}
NAME = re.compile(r"storepro-\d{8}-\d{6}-[a-f0-9]{6}\.zip")
LEGACY_UPLOAD = re.compile(r"uploads/[a-f0-9]{32}\.png")
GALLERY_UPLOAD = re.compile(
    r"uploads/products/\d+/(thumbs/)?[a-f0-9]{32}\.(png|jpg|jpeg|webp)"
)


def is_media_member(name):
    return bool(
        LEGACY_UPLOAD.fullmatch(name) or GALLERY_UPLOAD.fullmatch(name)
    )


def iter_gallery_files(root, connection):
    """Archive members for the multi-image gallery, derived from the snapshot."""
    tables = {
        r[0]
        for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "product_images" not in tables:
        return
    for product_id, file_name, file_path in connection.execute(
        "SELECT product_id, file_name, file_path FROM product_images"
    ):
        if (file_path or "").startswith("legacy:"):
            continue
        try:
            pid = int(product_id)
        except (TypeError, ValueError):
            continue
        if not re.fullmatch(r"[a-f0-9]{32}", Path(file_name or "").stem or ""):
            continue
        suffix = Path(file_name).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        for member in (
            f"uploads/products/{pid}/{file_name}",
            f"uploads/products/{pid}/thumbs/{file_name}",
        ):
            path = root / "static" / member
            if path.is_file():
                yield member, path
CRITICAL = {
    "permissions",
    "role_permissions",
    "user_permission_grants",
    "user_permission_denials",
    "endpoint_permissions",
    "products",
    "product_images",
    "sales",
    "sale_items",
    "sale_payments",
    "purchases",
    "purchase_items",
    "customers",
    "suppliers",
    "settings",
    "users",
    "roles",
    "categories",
    "inventory_movements",
    "expenses",
}


def stamp(value=None):
    return datetime.fromtimestamp(value or time.time(), timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    with pending.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def destinations(root, config):
    return {
        "Primary": Path(config.get("backup_primary") or root / "backups"),
        "Secondary": Path(config.get("backup_secondary") or root / "backups-secondary"),
    }


def validate_config(root, config):
    # Path rules are intentionally minimal: absolute, bounded length, no "..".
    # Backup destinations may live anywhere: any local drive, external USB
    # drives, or UNC network shares. Only writability decides suitability.
    paths = list(destinations(root, config).values())
    for path in paths:
        if len(str(path)) > 500 or any(c in str(path) for c in ("\x00", "\r", "\n")):
            raise ValueError(
                "Backup paths must be at most 500 characters without line breaks."
            )
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("Backup folders must be absolute paths without '..'.")
    a, b = (p.resolve() for p in paths)
    if a == b:
        raise ValueError(
            "Primary and secondary folders must be different destinations."
        )
    if config.get("backup_frequency") not in FREQUENCIES:
        raise ValueError("Choose a supported backup frequency.")
    try:
        if not 1 <= int(config.get("backup_retention", "50")) <= 10000:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("Retention must be between 1 and 10,000 backups per location.")


def probe(path):
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".storepro-write-", dir=path) as test:
        test.write(b"StorePro")
        test.flush()
        os.fsync(test.fileno())
    return shutil.disk_usage(path).free


def check_database(path):
    if not path.exists():
        return True
    if path.stat().st_size == 0:
        return False
    try:
        with closing(
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
        ) as con:
            row = con.execute("PRAGMA integrity_check(1)").fetchone()
            return bool(row and row[0] == "ok")
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "locked" in msg or "busy" in msg:
            # Concurrency lock contention is transient busy state, not corruption.
            return True
        return False
    except sqlite3.DatabaseError:
        return False


def inspect_archive(path, full=True):
    """No extraction; bound expansion and reject traversal/duplicate members."""
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [m.filename for m in members]
        if len(members) > 100000 or sum(m.file_size for m in members) > 8 * 1024**3:
            raise ValueError("Backup exceeds the 8 GB recovery limit.")
        if len(names) != len(set(names)) or "store.db" not in names:
            raise ValueError("Invalid backup members.")
        if any(
            m.file_size > 4 * 1024**2
            for m in members
            if m.filename in ("manifest.json", "settings.json", "configuration.json")
        ):
            raise ValueError("Backup metadata is too large.")
        for name in names:
            if name not in {
                "manifest.json",
                "store.db",
                "settings.json",
                "configuration.json",
            } and not is_media_member(name):
                raise ValueError("Unsafe archive member.")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != "StorePro" or manifest.get("version") not in (
            1,
            2,
        ):
            raise ValueError("Unsupported StorePro backup.")
        if full:
            if archive.testzip() is not None:
                raise ValueError("ZIP integrity check failed.")
            from PIL import Image

            for member in members:
                if member.filename.startswith("uploads/"):
                    if member.file_size > 32 * 1024**2:
                        raise ValueError("Backup contains an oversized image.")
                    with archive.open(member) as data, Image.open(data) as picture:
                        if picture.width * picture.height > 20_000_000:
                            raise ValueError("Backup contains an oversized image.")
                        picture.verify()
            if manifest.get("version") == 2:
                hashes = manifest.get("sha256", {})
                if set(hashes) != set(names) - {"manifest.json"}:
                    raise ValueError("Backup manifest is incomplete.")
                for name, expected in hashes.items():
                    h = hashlib.sha256()
                    with archive.open(name) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            h.update(chunk)
                    if h.hexdigest() != expected:
                        raise ValueError("Backup checksum mismatch.")
            with tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / "store.db"
                with archive.open("store.db") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if not check_database(target):
                    raise ValueError("Backup database is corrupt.")
                with closing(sqlite3.connect(target)) as con:
                    if con.execute("PRAGMA foreign_key_check").fetchall():
                        raise ValueError("Backup contains invalid database references.")
        return manifest


def make_archive(root, database, config, target):
    """Snapshot first; settings and media references come from that same snapshot."""
    with tempfile.TemporaryDirectory() as temp:
        snapshot = Path(temp) / "store.db"
        with (
            closing(sqlite3.connect(database, timeout=15)) as source,
            closing(sqlite3.connect(snapshot)) as dest,
        ):
            source.backup(dest, pages=128, sleep=0.02)
        with closing(sqlite3.connect(snapshot)) as con:
            values = DEFAULTS | dict(con.execute("SELECT key,value FROM settings"))
            images = {
                r[0]
                for r in con.execute(
                    "SELECT image FROM products WHERE image IS NOT NULL AND image != ''"
                )
            }
            if values.get("logo"):
                images.add(values["logo"])
            gallery_members = list(iter_gallery_files(root, con))
        hashes = {"store.db": digest(snapshot)}
        compression = (
            zipfile.ZIP_DEFLATED
            if config["backup_compression"] == "1"
            else zipfile.ZIP_STORED
        )
        with zipfile.ZipFile(target, "w", compression, allowZip64=True) as archive:
            archive.write(snapshot, "store.db")
            for name, payload in {
                "settings.json": values,
                "configuration.json": {
                    "format": 1,
                    "database": "SQLite",
                    "timezone": "Africa/Cairo",
                    "backup": {
                        k: v
                        for k, v in config.items()
                        if k.startswith("backup_") or k == "auto_backup"
                    },
                },
            }.items():
                data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(
                    "utf-8"
                )
                archive.writestr(name, data)
                hashes[name] = hashlib.sha256(data).hexdigest()
            # Include all immutable uploads, including logos in historic invoice snapshots.
            uploads = {p.name for p in (root / "static/uploads").glob("*.png")} | images
            members = {}
            for name in sorted(uploads):
                if not re.fullmatch(r"[a-f0-9]{32}\.png", name):
                    raise ValueError("An uploaded image has an invalid filename.")
                path = root / "static/uploads" / name
                if not path.is_file():
                    continue
                members["uploads/" + name] = path
            for member, path in gallery_members:
                if not is_media_member(member):
                    raise ValueError("An uploaded image has an invalid filename.")
                members[member] = path
            for member in sorted(members):
                path = members[member]
                hashes[member] = digest(path)
                archive.write(path, member)
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": "StorePro",
                        "version": 2,
                        "created": stamp(),
                        "sha256": hashes,
                    }
                ),
            )
    inspect_archive(target, full=config["backup_verification"] == "1")


def replicate(archive, folder, name, verify):
    """Copy one verified archive. Retention is unlimited: nothing is ever pruned."""
    pending = folder / ("." + name + ".partial")
    try:
        free = probe(folder)
        if free < archive.stat().st_size + 1024 * 1024:
            raise OSError("Disk full: insufficient space for the backup.")
        with archive.open("rb") as source, pending.open("xb") as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        # Readability and transport checks are mandatory even when deep verification is off.
        if digest(archive) != digest(pending):
            raise ValueError("Copied backup checksum mismatch.")
        inspect_archive(pending, full=verify)
        dest = folder / name
        pending.replace(dest)
        return {
            "source": "",
            "path": str(dest),
            "status": "Success",
            "size": dest.stat().st_size,
            "error": "",
        }
    except Exception as exc:
        return {
            "source": "",
            "path": str(folder / name),
            "status": "Failed",
            "size": 0,
            "error": str(exc),
        }
    finally:
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            pass


def run_backup(kind="Manual", reason="Manual"):
    app = current_app._get_current_object()
    root = app.config["ROOT"]
    config = settings()
    db.session.remove()  # Never hold a read transaction while copying large files.
    validate_config(root, config)
    name = f"storepro-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}.zip"
    folders = destinations(root, config)
    results = []
    with tempfile.TemporaryDirectory(dir=root / "instance") as temp:
        archive = Path(temp) / name
        try:
            make_archive(root, Path(db.engine.url.database), config, archive)
            with ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="StorePro-copy"
            ) as executor:
                jobs = {
                    source: executor.submit(
                        replicate,
                        archive,
                        path,
                        name,
                        config["backup_verification"] == "1",
                    )
                    for source, path in folders.items()
                }
                for source, job in jobs.items():
                    result = job.result()
                    result["source"] = source
                    results.append(result)
        except Exception as exc:
            results = [
                {
                    "source": source,
                    "path": str(path / name),
                    "status": "Failed",
                    "size": 0,
                    "error": str(exc),
                }
                for source, path in folders.items()
            ]
    for result in results:
        db.session.add(
            BackupLog(
                backup_id=name,
                kind=kind,
                reason=reason,
                status=result["status"],
                file_size=result["size"],
                location=result["path"],
                source=result["source"],
                error=result["error"],
            )
        )
    db.session.commit()
    db.session.remove()
    return results


def recovery_file(app):
    return app.config["ROOT"] / "instance/backup-recovery.json"


def read_recovery(app):
    try:
        return json.loads(recovery_file(app).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"config": DEFAULTS.copy(), "admins": []}


def save_recovery(app, config):
    from services.permissions import can

    admins = [
        {"username": u.username, "hash": u.password_hash}
        for u in User.query.filter_by(active=True).all()
        if can("backups.approve", u)
    ]
    atomic_json(recovery_file(app), {"config": config, "admins": admins})
    db.session.remove()


class BackupManager:
    def __init__(self, app):
        self.app = app
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.operation = threading.Lock()
        self.pending = True
        self.manual = False
        self.restore_job = None
        self.state = {
            "busy": False,
            "message": "Checking backup locations…",
            "locations": [],
            "files": [],
            "last_backup": None,
            "next_backup": None,
            "size": 0,
            "count": 0,
            "warnings": [],
        }
        self.next_due = time.time()
        self.schedule = None
        self.retry_at = 0
        self.last_check = 0

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def changed(self):
        with self.lock:
            self.pending = True
        self.wake.set()

    def enqueue(self):
        with self.lock:
            if self.state["busy"] or self.manual or self.restore_job:
                return False
            self.manual = True
            self.state.pop("restored", None)
            self.state["busy"] = True
            self.state["message"] = "Backup queued for both locations."
        self.wake.set()
        return True

    def restore(self, path, emergency=False, actor="Administrator"):
        with self.lock:
            if self.state["busy"] or self.manual or self.restore_job:
                raise ValueError("A backup or restore is already running. Please wait.")
            self.restore_job = (path, emergency, actor)
            self.state.pop("restored", None)
            self.state["busy"] = True
            self.state["message"] = "Verifying restore archive…"
        self.wake.set()

    def scan(self, config):
        locations, files, warnings = [], [], []
        paths = list(destinations(self.app.config["ROOT"], config).values())
        if paths[0].anchor.lower() == paths[1].anchor.lower():
            warnings.append(
                "Primary and Secondary destinations are located on the same physical drive. For maximum protection, choose different drives."
            )
        for source, folder in destinations(self.app.config["ROOT"], config).items():
            try:
                free = probe(folder)
                warning = free < 100 * 1024**2
                if warning:
                    warnings.append(source + " backup drive is low on free space.")
                folder_files = []
                for path in folder.glob("storepro-*.zip"):
                    if NAME.fullmatch(path.name) and not path.is_symlink():
                        stat = path.stat()
                        healthy = True
                        try:
                            inspect_archive(
                                path, full=bool(self.app.config.get("RECOVERY_MODE"))
                            )
                        except Exception:
                            healthy = False
                        entry = {
                            "name": path.name,
                            "source": source,
                            "size": stat.st_size,
                            "date": stamp(stat.st_mtime),
                            "healthy": healthy,
                        }
                        folder_files.append(entry)
                        files.append(entry)
                folder_files.sort(key=lambda f: f["date"], reverse=True)
                locations.append(
                    {
                        "source": source,
                        "path": str(folder),
                        "status": "Writable",
                        "warning": warning,
                        "free": free,
                        "count": len(folder_files),
                        "last_backup": folder_files[0]["date"]
                        if folder_files
                        else None,
                    }
                )
            except OSError as exc:
                locations.append(
                    {
                        "source": source,
                        "path": str(folder),
                        "status": "Unavailable",
                        "warning": False,
                        "free": 0,
                        "count": 0,
                        "last_backup": None,
                    }
                )
                warnings.append(source + " backup path unavailable: " + str(exc))
        files.sort(key=lambda f: f["date"], reverse=True)
        if self.app.config.get("RECOVERY_MODE"):
            warnings.insert(
                0,
                "Database corruption detected. Choose a healthy recovery point below.",
            )
        else:
            for source in ("Primary", "Secondary"):
                latest = (
                    BackupLog.query.filter_by(source=source)
                    .order_by(BackupLog.id.desc())
                    .first()
                )
                if latest and (latest.status == "Failed" or latest.error):
                    warnings.append(source + ": " + (latest.error or "Backup failed."))
            db.session.remove()
        healthy_files = [f for f in files if f["healthy"]]
        if len(healthy_files) < len(files):
            warnings.append(
                "One or more backup archives are unreadable. Choose a healthy recovery point."
            )
        self.update(
            locations=locations,
            files=files,
            count=len(files),
            warnings=warnings,
            last_backup=healthy_files[0]["date"] if healthy_files else None,
            size=healthy_files[0]["size"] if healthy_files else 0,
        )
        if self.snapshot()["message"] == "Checking backup locations…":
            self.update(message="Backup destinations checked.")

    def tick(self):
        with self.lock:
            restore = self.restore_job
            self.restore_job = None
        if restore:
            path, emergency, actor = restore
            try:
                from services.backups import restore_backup

                with self.operation:
                    restore_backup(path, emergency=emergency)
                self.app.config["RECOVERY_MODE"] = False
                db.session.add(
                    AuditLog(
                        actor=actor,
                        action="Restore completed",
                        details=f"Validated {path.name}; all sessions invalidated",
                    )
                )
                db.session.commit()
                db.session.remove()
                self.update(message="Restore completed. Sign in again.", restored=True)
                self.pending = True
            except Exception as exc:
                self.app.logger.exception("Restore failed")
                self.update(message="Restore failed: " + str(exc), restored=False)
                if not self.app.config.get("RECOVERY_MODE"):
                    db.session.rollback()
                    db.session.add(
                        AuditLog(actor=actor, action="Restore failed", details=str(exc))
                    )
                    db.session.commit()
            finally:
                self.update(busy=False)
                self.last_check = 0
                if path.parent == self.app.config["ROOT"] / "instance/restore-staging":
                    path.unlink(missing_ok=True)
            return
        if self.app.config.get("RECOVERY_MODE"):
            if time.time() - self.last_check > 30:
                self.scan(read_recovery(self.app)["config"])
                self.last_check = time.time()
            return
        config = settings()
        if time.time() - self.last_check > 30 or self.pending:
            save_recovery(self.app, config)
            self.scan(config)
            self.last_check = time.time()
        if not User.query.filter_by(active=True).first():
            db.session.remove()
            self.pending = False
            return
        schedule = (config["auto_backup"], config["backup_frequency"])
        if schedule != self.schedule:
            self.schedule = schedule
            latest = (
                BackupLog.query.filter_by(reason="Scheduled", status="Success")
                .order_by(BackupLog.id.desc())
                .first()
            )
            base = (
                latest.created_at.replace(tzinfo=timezone.utc).timestamp()
                if latest
                else time.time()
            )
            self.next_due = base + FREQUENCIES[config["backup_frequency"]]
            try:
                persisted = json.loads(
                    (
                        self.app.config["ROOT"] / "instance/backup-schedule.json"
                    ).read_text()
                )
                if persisted["schedule"] == list(schedule) and isinstance(
                    persisted["next_due"], (int, float)
                ):
                    self.next_due = persisted["next_due"]
            except (OSError, ValueError, KeyError):
                pass
            self.persist_schedule()
        db.session.remove()
        scheduled = config["auto_backup"] == "1" and time.time() >= self.next_due
        with self.lock:
            manual = self.manual
            live = self.pending and config["backup_live"] == "1"
            ready = manual or ((live or scheduled) and time.time() >= self.retry_at)
            if ready:
                self.pending = self.manual = False
                self.state["busy"] = True
            elif config["backup_live"] != "1":
                self.pending = False
        self.update(
            next_backup=stamp(self.next_due) if config["auto_backup"] == "1" else None
        )
        if ready:
            reason = "Manual" if manual else "Scheduled" if scheduled else "Live"
            try:
                self.update(message="Creating and verifying both backup copies…")
                with self.operation:
                    from services.job_monitor import job_monitor
                    with job_monitor.track("backups", "Dual encrypted backup snapshots and replicas", "Live & Scheduled"):
                        results = run_backup("Manual" if manual else "Auto", reason)
                successful = sum(r["status"] == "Success" for r in results)
                self.update(
                    message=f"Backup complete: {successful}/2 destinations succeeded."
                )
                if successful < 2:
                    self.pending = True
                    self.retry_at = time.time() + 60
                else:
                    self.retry_at = 0
                if scheduled and successful == 2:
                    self.next_due = (
                        time.time() + FREQUENCIES[config["backup_frequency"]]
                    )
                    self.persist_schedule()
                self.scan(config)
            finally:
                self.update(
                    busy=False,
                    next_backup=stamp(self.next_due)
                    if config["auto_backup"] == "1"
                    else None,
                )

    def persist_schedule(self):
        atomic_json(
            self.app.config["ROOT"] / "instance/backup-schedule.json",
            {"schedule": self.schedule, "next_due": self.next_due},
        )

    def worker(self):
        while not self.stop.is_set():
            try:
                with self.app.app_context():
                    self.tick()
            except Exception as exc:
                self.app.logger.exception("Backup worker failed")
                self.pending = True
                self.update(
                    busy=False,
                    message="Backup failed: " + str(exc),
                    warnings=["Backup failed: " + str(exc)],
                )
                self.retry_at = time.time() + 60
            # Bound bursts: changes committed during a backup remain pending.
            self.wake.wait(2)
            self.wake.clear()
            self.stop.wait(1)


def initialize(app, start=True):
    manager = app.extensions.get("backups")
    if manager:
        return manager
    (app.config["ROOT"] / "instance").mkdir(parents=True, exist_ok=True)
    manager = app.extensions["backups"] = BackupManager(app)
    from services.job_monitor import job_monitor
    job_monitor.register("backups", "Dual encrypted backup snapshots and replicas", "Live & Scheduled")
    if start:
        thread = threading.Thread(
            target=manager.worker, name="StorePro-backups", daemon=True
        )
        thread.start()
        manager.thread = thread
    return manager


@event.listens_for(Session, "before_flush")
def collect_changes(session, context, instances):
    if any(
        getattr(obj, "__tablename__", "") in CRITICAL
        and (obj in session.new or obj in session.deleted or session.is_modified(obj))
        for obj in session.new | session.dirty | session.deleted
    ):
        session.info["backup_dirty"] = True


@event.listens_for(Session, "after_commit")
def committed(session):
    if session.info.pop("backup_dirty", False) and has_app_context():
        manager = current_app.extensions.get("backups")
        if manager:
            manager.changed()


@event.listens_for(Session, "do_orm_execute")
def bulk_changes(state):
    if state.is_update or state.is_delete:
        table = getattr(state.statement, "table", None)
        if table is not None and table.name in CRITICAL:
            state.session.info["backup_dirty"] = True


@event.listens_for(Session, "after_rollback")
def rolled_back(session):
    session.info.pop("backup_dirty", None)
