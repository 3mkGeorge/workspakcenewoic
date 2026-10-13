"""Automated Database Maintenance & Backup Verification Scheduler.

Provides scheduled and on-demand execution of:
- SQLite WAL checkpoints (TRUNCATE mode to prevent unbounded disk growth)
- PRAGMA optimize (Query planner statistical updates)
- VACUUM and REINDEX (Compacting space & rebuilding index B-trees)
- PRAGMA integrity_check & foreign_key_check
- Automated backup verification across Primary and Secondary vaults
"""

import logging
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from services.job_monitor import job_monitor

logger = logging.getLogger("storepro.maintenance")


def checkpoint_wal(db_path, mode="TRUNCATE"):
    """Flush WAL journal pages into main store.db and truncate WAL file."""
    db_file = Path(db_path)
    if not db_file.exists():
        return False, "Database file does not exist"
    
    with closing(sqlite3.connect(str(db_file), timeout=15.0)) as conn:
        cursor = conn.cursor()
        res = cursor.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        # Returns (busy, log_pages, checkpointed_pages)
        busy, log_pages, checkpointed = res
        msg = f"WAL Checkpoint ({mode}): busy={busy}, log={log_pages}, checkpointed={checkpointed}"
        logger.info(msg)
        return (busy == 0), msg


def optimize_database(db_path):
    """Run PRAGMA optimize to refresh query planner statistics."""
    db_file = Path(db_path)
    if not db_file.exists():
        return False, "Database file not found"
    
    with closing(sqlite3.connect(str(db_file), timeout=15.0)) as conn:
        conn.execute("PRAGMA optimize")
        logger.info("PRAGMA optimize completed successfully.")
        return True, "PRAGMA optimize executed"


def vacuum_database(db_path):
    """Run VACUUM to reclaim deleted pages and defragment database."""
    db_file = Path(db_path)
    if not db_file.exists():
        return False, "Database file not found"
    
    with closing(sqlite3.connect(str(db_file), timeout=30.0)) as conn:
        conn.isolation_level = None  # Autocommit mode required for VACUUM
        conn.execute("VACUUM")
        logger.info("Database VACUUM completed successfully.")
        return True, "Database VACUUM completed"


def reindex_database(db_path):
    """Run REINDEX to rebuild all database indexes."""
    db_file = Path(db_path)
    if not db_file.exists():
        return False, "Database file not found"
    
    with closing(sqlite3.connect(str(db_file), timeout=30.0)) as conn:
        conn.isolation_level = None
        conn.execute("REINDEX")
        logger.info("Database REINDEX completed successfully.")
        return True, "Database REINDEX completed"


def verify_integrity(db_path):
    """Run PRAGMA integrity_check and PRAGMA foreign_key_check."""
    db_file = Path(db_path)
    if not db_file.exists():
        return False, ["Database file not found"]
    
    errors = []
    with closing(sqlite3.connect(str(db_file), timeout=15.0)) as conn:
        # Check foreign keys
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            errors.append(f"Foreign key violations detected: {len(fk_violations)}")
        
        # Check B-tree integrity
        res = conn.execute("PRAGMA integrity_check(10)").fetchall()
        if not res or res[0][0] != "ok":
            errors.extend([r[0] for r in res])
    
    return len(errors) == 0, errors


def verify_all_backup_archives(app):
    """Inspect and cryptographically verify all existing backup archives."""
    from services.dual_backup import inspect_archive
    from models import db, BackupLog

    root = Path(app.config.get("ROOT", Path(".")))
    destinations = [root / "backups", root / "backups-secondary"]
    
    total_checked = 0
    verified_healthy = 0
    failures = []

    for dest in destinations:
        if not dest.is_dir():
            continue
        for archive in dest.glob("*.zip"):
            total_checked += 1
            try:
                # Inspect archive structure, size bounds, and media
                inspect_archive(archive, full=True)
                verified_healthy += 1
            except Exception as exc:
                err_msg = f"Backup integrity failure on {archive.name}: {str(exc)}"
                failures.append(err_msg)
                logger.error(err_msg)
                try:
                    with app.app_context():
                        log = BackupLog(
                            backup_id=archive.stem,
                            kind="Auto",
                            reason="Verification",
                            status="Failed",
                            file_size=archive.stat().st_size if archive.exists() else 0,
                            location=str(archive),
                            source="Primary" if "secondary" not in str(dest) else "Secondary",
                            error=str(exc)[:500],
                        )
                        db.session.add(log)
                        db.session.commit()
                except Exception:
                    pass

    return {
        "total": total_checked,
        "healthy": verified_healthy,
        "failures": failures,
    }


def run_full_database_maintenance(db_path):
    """Execute complete maintenance pipeline."""
    results = {}
    
    # 1. Integrity verification
    ok, errs = verify_integrity(db_path)
    results["integrity"] = "Passed" if ok else f"Failed: {errs}"
    if not ok:
        return results
    
    # 2. Optimize
    opt_ok, opt_msg = optimize_database(db_path)
    results["optimize"] = opt_msg
    
    # 3. WAL Checkpoint
    chk_ok, chk_msg = checkpoint_wal(db_path, "TRUNCATE")
    results["checkpoint"] = chk_msg
    
    # 4. Reindex
    reindex_ok, reindex_msg = reindex_database(db_path)
    results["reindex"] = reindex_msg

    # 5. Vacuum
    vac_ok, vac_msg = vacuum_database(db_path)
    results["vacuum"] = vac_msg

    return results


class MaintenanceScheduler:
    """Background thread running periodic DB maintenance and backup verifications."""

    def __init__(self, app, interval_hours=24):
        self.app = app
        self.interval_seconds = interval_hours * 3600
        self.stop_event = threading.Event()
        self.thread = None

        # Register jobs with job monitor
        job_monitor.register(
            "db_maintenance",
            "Automatic database WAL checkpoint, PRAGMA optimize, vacuum and reindex",
            f"Every {interval_hours} Hours"
        )
        job_monitor.register(
            "backup_verifier",
            "Cryptographic and structural verification of backup archives",
            f"Every {interval_hours} Hours"
        )

    def start(self):
        self.thread = threading.Thread(
            target=self._run_loop, name="StorePro-maintenance", daemon=True
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

    def _run_loop(self):
        # Initial sleep before first run to let app start up smoothly
        self.stop_event.wait(30)
        while not self.stop_event.is_set():
            try:
                db_path = self.app.config.get("ROOT", Path(".")) / "instance" / "store.db"
                
                # Run DB maintenance
                with job_monitor.track("db_maintenance", "Database optimization & checkpoint"):
                    run_full_database_maintenance(db_path)
                
                # Run Backup verification
                with job_monitor.track("backup_verifier", "Backup integrity validation"):
                    verify_all_backup_archives(self.app)

            except Exception as exc:
                logger.exception("Scheduled maintenance encountered an error")

            # Wait for next interval or stop signal
            self.stop_event.wait(self.interval_seconds)


def initialize_maintenance(app, start=True):
    """Attach maintenance scheduler to Flask application."""
    existing = app.extensions.get("maintenance")
    if existing:
        return existing
    scheduler = MaintenanceScheduler(app)
    app.extensions["maintenance"] = scheduler
    if start and not app.config.get("TESTING"):
        scheduler.start()
    return scheduler
