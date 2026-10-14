"""Consistent SQLite snapshots, local media, validated restores, and daily scheduling."""

import json
import sqlite3
import tempfile
import secrets
import zipfile
from contextlib import closing
from pathlib import Path
from flask import current_app
from models import db


def database_path():
    return Path(db.engine.url.database)


def _media_member(name):
    from services.dual_backup import is_media_member

    return is_media_member(name)


def create_backup():
    """Synchronous internal recovery point; UI calls enqueue background work."""
    from services.dual_backup import run_backup

    results = run_backup()
    healthy = [r for r in results if r["status"] == "Success"]
    if not healthy:
        raise ValueError("No recovery backup could be saved: " + results[0]["error"])
    return Path(healthy[0]["path"])


def restore_backup(file, emergency=False):
    root = current_app.config["ROOT"]
    from services.dual_backup import inspect_archive

    try:
        inspect_archive(file, full=True)
        if hasattr(file, "seek"):
            file.seek(0)
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(file) as z:
            members = z.infolist()
            if len(members) > 100000 or sum(x.file_size for x in members) > 8 * 1024**3:
                raise ValueError("Backup is too large.")
            names = [m.filename for m in members]
            if len(names) != len(set(names)):
                raise ValueError("Backup has duplicate entries.")
            if json.loads(z.read("manifest.json")).get("version") not in (1, 2):
                raise ValueError("Unsupported backup version.")
            for member in members:
                name = member.filename
                if name not in (
                    "store.db",
                    "manifest.json",
                    "settings.json",
                    "configuration.json",
                ) and not (
                    _media_member(name)
                ):
                    raise ValueError("Backup contains an invalid file.")
            source = Path(tmp) / "store.db"
            import shutil

            with z.open("store.db") as input_db, source.open("wb") as output_db:
                shutil.copyfileobj(input_db, output_db)
            # Older StorePro snapshots gain the additive POS schema before validation.
            with closing(sqlite3.connect(source)) as initial:
                from services.migrations import validate_database_objects

                validate_database_objects(initial)
            from services.migrations import upgrade_sqlite

            upgrade_sqlite(source)
            with closing(sqlite3.connect(source)) as check:
                if (
                    check.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or check.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise ValueError("Backup database failed validation.")
                validate_database_objects(check)
                tables = {
                    r[0]
                    for r in check.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                if tables != set(db.metadata.tables):
                    raise ValueError("Unexpected database tables in backup.")
                for table in db.metadata.sorted_tables:
                    columns = {
                        r[1]
                        for r in check.execute(f'PRAGMA table_info("{table.name}")')
                    }
                    if columns != {c.name for c in table.columns}:
                        raise ValueError(
                            "The backup schema is not compatible with this application."
                        )
                if not check.execute(
                    "SELECT 1 FROM users u WHERE u.active=1 AND (SELECT COUNT(*) FROM permissions WHERE key IN ('users.permissions','backups.approve'))=2 AND NOT EXISTS (SELECT 1 FROM permissions p WHERE p.key IN ('users.permissions','backups.approve') AND (EXISTS (SELECT 1 FROM user_permission_denials d WHERE d.user_id=u.id AND d.permission_id=p.id) OR NOT (EXISTS (SELECT 1 FROM user_permission_grants g WHERE g.user_id=u.id AND g.permission_id=p.id) OR EXISTS (SELECT 1 FROM role_permissions r WHERE r.role_id=u.role_id AND r.permission_id=p.id))))"
                ).fetchone():
                    raise ValueError("Backup has no active access and recovery operator.")
                if check.execute(
                    "SELECT 1 FROM products WHERE stock<0 OR cost<0 OR price<0 LIMIT 1"
                ).fetchone():
                    raise ValueError("Backup contains invalid inventory.")
                if (
                    check.execute(
                        # Payments must add up to each invoice total. Partial refunds
                        # made before refunds reduced the payment rows left the full
                        # original payment recorded; that known, benign footprint is
                        # accepted so those stores' backups stay restorable.
                        "SELECT 1 FROM sales s JOIN sale_payments p ON p.sale_id=s.id "
                        "GROUP BY s.id HAVING SUM(p.amount) != s.total "
                        "AND NOT (SUM(p.amount) > s.total AND s.note LIKE '%[Partial refund:%') "
                        "LIMIT 1"
                    ).fetchone()
                    or check.execute(
                        "SELECT 1 FROM sales s JOIN sale_items i ON i.sale_id=s.id "
                        "GROUP BY s.id HAVING SUM(i.discount)>s.discount LIMIT 1"
                    ).fetchone()
                ):
                    raise ValueError(
                        "Backup contains inconsistent invoice allocations."
                    )
                from services.core import DEFAULTS, integer, cents

                config = DEFAULTS | dict(
                    check.execute("SELECT key,value FROM settings")
                )
                integer(config["session_minutes"], 5, 480)
                integer(config["items_per_page"], 5, 100)
                if (
                    config["currency"] not in ("EGP", "USD", "EUR", "SAR", "AED")
                    or config["language"] not in ("en", "ar")
                    or cents(config["tax_rate"]) > 10000
                ):
                    raise ValueError("Backup contains invalid settings.")
            # Validate images before changing any live database state.
            from PIL import Image

            media = {}
            for name in names:
                if name.startswith("uploads/"):
                    staged_image = Path(tmp) / Path(*Path(name).parts)
                    staged_image.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        z.open(name) as input_image,
                        staged_image.open("wb") as output_image,
                    ):
                        shutil.copyfileobj(input_image, output_image)
                    with Image.open(staged_image) as img:
                        img.verify()
                    media[name] = staged_image
            # The expensive archive validation above is outside the request lock.
            # Freeze writes only for the recovery point and final database replacement.
            with current_app.config["DB_LOCK"]:
                # Backup paths are machine-specific. Preserve this installation's
                # destinations while restoring all store/business settings.
                from services.dual_backup import read_recovery, validate_config
                from services.core import settings

                local_config = (
                    read_recovery(current_app)["config"] if emergency else settings()
                )
                validate_config(root, local_config)
                with closing(sqlite3.connect(source)) as staged:
                    for key, value in local_config.items():
                        if key.startswith("backup_") or key == "auto_backup":
                            staged.execute(
                                "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                (key, value),
                            )
                    staged.commit()
                if not emergency:
                    # A fast local online snapshot is the emergency rollback point.
                    recovery = (
                        root
                        / "instance"
                        / ("pre-restore-" + secrets.token_hex(8) + ".sqlite3")
                    )
                    with (
                        closing(sqlite3.connect(database_path())) as live,
                        closing(sqlite3.connect(recovery)) as saved,
                    ):
                        live.backup(saved)
                db.session.remove()
                db.engine.dispose()
                (root / "static/uploads").mkdir(parents=True, exist_ok=True)
                from services.dual_backup import digest

                for name, image in media.items():
                    target = root / "static" / Path(*Path(name).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and digest(target) != digest(image):
                        raise ValueError(
                            "Backup image conflicts with an existing immutable upload."
                        )
                    shutil.copy2(image, target)
                if emergency:
                    # Preserve damaged database and its journals for offline investigation.
                    damaged = root / "instance" / ("corrupt-" + secrets.token_hex(8))
                    damaged.mkdir()
                    live_path = database_path()
                    for suffix in ("", "-wal", "-shm"):
                        old = Path(str(live_path) + suffix)
                        if old.exists():
                            shutil.copy2(old, damaged / old.name)
                    replacement = live_path.with_suffix(".recovered")
                    shutil.copy2(source, replacement)
                    for suffix in ("-wal", "-shm"):
                        Path(str(live_path) + suffix).unlink(missing_ok=True)
                    replacement.replace(live_path)
                else:
                    with (
                        closing(sqlite3.connect(source)) as source_db,
                        closing(sqlite3.connect(database_path())) as destination,
                    ):
                        source_db.backup(destination)
                db.engine.dispose()
                current_app.config["AUTH_EPOCH"] = secrets.token_hex(16)

    except (
        zipfile.BadZipFile,
        KeyError,
        sqlite3.DatabaseError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        raise ValueError("This is not a valid StorePro backup.") from exc


def start_backups(app):
    from services.dual_backup import initialize

    return initialize(app)
