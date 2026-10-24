"""Maintenance CLI; run from the application folder."""

import argparse
from pathlib import Path
from app import create_app
from models import db, User


def main():
    parser = argparse.ArgumentParser(description="StorePro maintenance")
    parser.add_argument("command", choices=["demo", "schema", "backup", "verify", "web-sync"])
    parser.add_argument(
        "--confirm-demo",
        action="store_true",
        help="Confirm sample data should be added to an empty catalog",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="web-sync: build and check the website snapshot without sending anything",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="web-sync: show configuration (without the secret) and the last sync result",
    )
    args = parser.parse_args()
    app = create_app({"BACKUP_WORKER": False})
    with app.app_context():
        if args.command == "demo":
            if not args.confirm_demo:
                parser.error(
                    "Use --confirm-demo only for an empty demonstration store, never a live store."
                )
            user = User.query.filter_by(active=True).first()
            if not user:
                parser.error("Create your administrator account in the browser first.")
            from services.demo import seed_demo

            seed_demo(user)
            print("Demonstration data loaded. Refresh the dashboard.")
        elif args.command == "schema":
            from sqlalchemy.schema import CreateTable, CreateIndex

            text = "-- StorePro SQLite schema. Application startup creates the same schema.\nPRAGMA foreign_keys = ON;\n\n"
            for table in db.metadata.sorted_tables:
                text += str(CreateTable(table).compile(db.engine)) + ";\n"
                for index in table.indexes:
                    text += str(CreateIndex(index).compile(db.engine)) + ";\n"
            from services.migrations import PRICE_TRIGGERS

            text += "\n".join(sql + ";" for sql in PRICE_TRIGGERS.values()) + "\n"
            Path("schema.sql").write_text(text, encoding="utf-8")
            print("schema.sql generated.")
        elif args.command == "web-sync":
            from services.web_catalog_sync import load_config, load_state, run_sync, website_status

            cfg = load_config()
            if args.status:
                public = cfg.public()
                print(f"Enabled:            {'yes' if public['enabled'] else 'no'}")
                print(f"Website URL:        {public['url'] or '(not configured)'}")
                print(f"Secret configured:  {'yes' if public['secret_configured'] else 'no'}")
                for problem in public["problems"]:
                    print(f"Configuration issue: {problem}")
                state = load_state()
                for key in ("last_success_at", "last_failure_at", "last_error", "last_snapshot_id", "last_product_count", "last_result"):
                    print(f"{key + ':':<20}{state.get(key, '—')}")
                remote, error = website_status(cfg)
                print(f"Website reports:    {remote if remote else error}")
                return
            result = run_sync("cli", dry_run=args.dry_run)
            if args.dry_run:
                print(
                    f"Dry run: {result['products']} products, {result['categories']} categories, "
                    f"{result['brands']} brands, {result['images']} images (snapshot {result['snapshot_id']})."
                )
            elif result.get("ok"):
                state = result["state"]
                print(f"Website sync {state.get('last_result')}: {state.get('last_product_count')} products published (snapshot {state.get('last_snapshot_id')}).")
            else:
                print(f"Website sync failed: {result.get('error')}")
            for warning in result.get("warnings") or result.get("state", {}).get("last_warnings", []):
                print(f"  warning: {warning}")
            if not result.get("ok"):
                raise SystemExit(1)
        elif args.command == "verify":
            from services.dual_backup import check_database
            import sqlite3
            from contextlib import closing

            db_file = Path(db.engine.url.database)
            if not db_file.exists():
                print("Database file does not exist yet.")
                return
            ok = check_database(db_file)
            print(f"Database file: {db_file}")
            print(f"Integrity check: {'PASSED' if ok else 'FAILED'}")
            with closing(sqlite3.connect(db_file)) as conn:
                fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                print(f"Foreign key check: {'PASSED' if not fk_violations else f'FAILED ({len(fk_violations)} violations)'}")
            if not ok or fk_violations:
                raise SystemExit(1)
        else:
            from services.dual_backup import run_backup, save_recovery
            from services.core import settings

            save_recovery(app, settings())
            results = run_backup()
            for result in results:
                print(f"{result['source']}: {result['status']} — {result['path']}")
                if result["error"]:
                    print(result["error"])
            if any(r["status"] != "Success" for r in results):
                raise SystemExit(1)


if __name__ == "__main__":
    from services.process_lock import store_lock

    with store_lock(Path(__file__).resolve().parent / "instance/server.lock"):
        main()
