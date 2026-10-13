"""StorePro Local User Recovery Utility.

Allows local workstation operators to discover forgotten usernames and reset
user passwords without compromising RBAC roles, data integrity, or security.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app
from models import Role, User, db
from services.core import audit
from services.process_lock import store_lock


MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def validate_password_policy(password: str) -> None:
    """Validate password against StorePro's standard password policy (12-128 chars)."""
    if not password or len(password) < MIN_PASSWORD_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Use a password with {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters."
        )


def get_user_display_list() -> list[dict[str, Any]]:
    """Retrieve existing users with role and status information (no password hashes)."""
    users = User.query.order_by(User.id).all()
    output = []
    for u in users:
        role_name = u.role.name if u.role else "None"
        output.append({
            "id": u.id,
            "username": u.username,
            "name": u.name,
            "role": role_name,
            "active": bool(u.active),
            "version": u.version or 1,
        })
    return output


def print_users_table(user_list: list[dict[str, Any]]) -> None:
    """Display user table without exposing sensitive credentials or hashes."""
    if not user_list:
        print("\nStorePro is currently unprovisioned (0 users found in database).")
        print("Please run StorePro via run.bat to complete initial administrator setup.")
        return

    print("\nExisting StorePro Users:")
    header = f"{'ID':<6} | {'Username':<22} | {'Name':<24} | {'Role':<14} | {'Active':<8}"
    separator = f"{'-'*6}-+-{'-'*22}-+-{'-'*24}-+-{'-'*14}-+-{'-'*8}"
    print(header)
    print(separator)
    for u in user_list:
        active_str = "Yes" if u["active"] else "No"
        print(f"{u['id']:<6} | {u['username']:<22} | {u['name']:<24} | {u['role']:<14} | {active_str:<8}")
    print()


def find_user_by_identifier(identifier: str | int) -> User | None:
    """Find user by numeric ID or username (case-insensitive)."""
    if isinstance(identifier, int):
        return db.session.get(User, identifier)

    clean_id = str(identifier).strip()
    if clean_id.isdigit():
        user = db.session.get(User, int(clean_id))
        if user:
            return user

    return User.query.filter_by(username=clean_id.lower()).first()


def create_pre_reset_backup(app) -> str | None:
    """Create safety database backups before any modification."""
    db_file = Path(db.engine.url.database)
    if not db_file.exists():
        return None

    # 1. Standalone SQLite snapshot backup (with WAL consistency)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_bak_name = f"store.db.pre_reset_{timestamp}.bak"
    local_bak_path = db_file.parent / local_bak_name

    # Ensure never overwriting an existing file
    counter = 1
    while local_bak_path.exists():
        local_bak_name = f"store.db.pre_reset_{timestamp}_{counter}.bak"
        local_bak_path = db_file.parent / local_bak_name
        counter += 1

    try:
        with sqlite3.connect(str(db_file)) as src, sqlite3.connect(str(local_bak_path)) as dst:
            src.backup(dst)
        print(f"Safety SQLite snapshot created: {local_bak_path.name}")
    except Exception:
        shutil.copy2(db_file, local_bak_path)
        print(f"Safety file copy created: {local_bak_path.name}")

    # 2. Attempt dual backup engine if available
    try:
        from services.core import settings
        from services.dual_backup import run_backup, save_recovery

        save_recovery(app, settings())
        results = run_backup(kind="Manual", reason="Pre-password reset recovery backup")
        for res in results:
            if res.get("status") == "Success" and res.get("path"):
                print(f"Dual backup archive created: {Path(res['path']).name}")
    except Exception as exc:
        print(f"[Backup Notice] Dual backup could not run: {exc}")

    # Clean up scoped session so subsequent DB operations begin with a fresh active session
    db.session.remove()

    return str(local_bak_path)


def execute_password_reset(
    user_identifier: str | int,
    new_password: str,
    confirm_password: str,
    create_backup: bool = True,
    app=None,
) -> tuple[bool, str]:
    """Safely reset password for a single user with complete rollback protection."""
    # 1. Validate inputs
    if new_password != confirm_password:
        return False, "Passwords do not match."

    try:
        validate_password_policy(new_password)
    except ValueError as ve:
        return False, str(ve)

    # 2. Initial lookup to verify user exists
    initial_user = find_user_by_identifier(user_identifier)
    if not initial_user:
        return False, f"User '{user_identifier}' not found."

    target_user_id = initial_user.id

    # Verify exactly one user record is targeted
    count = User.query.filter_by(id=target_user_id).count()
    if count != 1:
        return False, f"Integrity check failed: Expected 1 user record, found {count}."

    # 3. Create safety SQLite snapshot before modifying the database
    safety_snapshot_path = None
    if create_backup and app:
        safety_snapshot_path = create_pre_reset_backup(app)

    # 4. Begin DB transaction: re-query user afresh in the active session after backup routines
    try:
        user = db.session.get(User, target_user_id)
        if not user:
            return False, f"User ID {target_user_id} not found in database session."

        db.session.add(user)

        # 5. Generate password hash using StorePro's standard Werkzeug hashing scheme
        hashed = generate_password_hash(new_password)

        # 6. Assign hash
        user.password_hash = hashed

        # 7. Increment session version to invalidate existing active sessions
        user.version = (user.version or 1) + 1

        audit(
            "Password Reset (Recovery Utility)",
            f"Password reset for user '{user.username}' (ID: {user.id}) via local recovery utility",
        )

        # 8. Commit
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return False, f"Database transaction failed and was rolled back: {exc}"

    # 9. Reload user from DB (expiring all identity-map cache to force fresh SELECT)
    try:
        db.session.expire_all()
        persisted_user = db.session.get(User, target_user_id)

        # 10. Verify persisted password hash against entered password
        if not persisted_user:
            raise ValueError("User not found after commit.")

        if not check_password_hash(persisted_user.password_hash, new_password):
            raise ValueError("Password hash does not validate against entered password.")

        if persisted_user.password_hash == new_password:
            raise ValueError("Security violation: Password was stored in plaintext.")

    except Exception as verify_err:
        # Revert change if verification fails
        if safety_snapshot_path and Path(safety_snapshot_path).exists():
            try:
                db_file = Path(db.engine.url.database)
                db.session.remove()
                shutil.copy2(safety_snapshot_path, db_file)
            except Exception as restore_err:
                print(f"[CRITICAL] Snapshot restore error: {restore_err}")

        return False, f"Post-reset verification failed: {verify_err}"

    # 11. Return success with the persisted username
    return True, persisted_user.username


def interactive_menu(app) -> int:
    """Run the interactive console menu for user recovery."""
    print("=" * 60)
    print("StorePro Local User Recovery Utility")
    print("=" * 60)

    while True:
        print("\nOptions:")
        print("  [L] List users")
        print("  [R] Reset password")
        print("  [Q] Quit")
        try:
            choice = input("\nEnter choice [L/R/Q]: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting recovery utility.")
            return 0

        if choice in ("L", "1"):
            users = get_user_display_list()
            print_users_table(users)

        elif choice in ("R", "2"):
            users = get_user_display_list()
            if not users:
                print("\nStorePro is currently unprovisioned (0 users found in database).")
                print("Run StorePro via run.bat to complete first-run setup.")
                continue

            try:
                target = input("Enter User ID or Username to reset (or press Enter to cancel): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nOperation cancelled.")
                continue

            if not target:
                print("Operation cancelled.")
                continue

            user = find_user_by_identifier(target)
            if not user:
                print(f"Error: No user found matching '{target}'.")
                continue

            role_name = user.role.name if user.role else "None"
            active_str = "Yes" if user.active else "No"
            print("\nSelected User Details:")
            print(f"  ID:           {user.id}")
            print(f"  Username:     {user.username}")
            print(f"  Display Name: {user.name}")
            print(f"  Role:         {role_name}")
            print(f"  Active:       {active_str}")
            print(f"  Version:      {user.version}")

            try:
                confirm = input("\nReset password for this user? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nOperation cancelled.")
                continue

            if confirm not in ("y", "yes"):
                print("Password reset cancelled (defaulting to No).")
                continue

            try:
                pwd1 = getpass.getpass("Enter new password (min 12 characters): ")
                pwd2 = getpass.getpass("Confirm new password: ")
            except (EOFError, KeyboardInterrupt):
                print("\nOperation cancelled.")
                continue

            success, message = execute_password_reset(
                user.id, pwd1, pwd2, create_backup=True, app=app
            )

            if success:
                print("\n" + "=" * 50)
                print("PASSWORD RESET SUCCESSFUL")
                print("=" * 50)
                print(f"Username:            {message}")
                print("Session status:      Previous sessions invalidated")
                print("Storage security:    Hashed via Werkzeug (never stored in plaintext)")
                print("=" * 50)
            else:
                print(f"\nError: {message}")

        elif choice in ("Q", "3", "QUIT", "EXIT"):
            print("Exiting recovery utility.")
            return 0
        else:
            print("Invalid selection. Please choose L, R, or Q.")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for recovery utility."""
    parser = argparse.ArgumentParser(description="StorePro Local User Recovery Utility")
    parser.add_argument("--list", action="store_true", help="List existing users and exit")
    parser.add_argument("--user", type=str, help="User ID or username to reset")
    parser.add_argument("--password", type=str, help="New password (for automated testing)")
    parser.add_argument("--confirm-password", type=str, help="Confirm new password")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup creation")

    args = parser.parse_args(argv)

    root = PROJECT_ROOT
    db_file = root / "instance" / "store.db"
    if not db_file.exists():
        print("StorePro database file does not exist (instance/store.db).")
        print("StorePro is currently unprovisioned. Run StorePro first via run.bat to complete first-run setup.")
        return 0

    lock_file = root / "instance" / "server.lock"

    with store_lock(lock_file):
        app = create_app({"BACKUP_WORKER": False})
        with app.app_context():
            if args.list:
                users = get_user_display_list()
                print_users_table(users)
                return 0

            if args.user:
                if not args.password or not args.confirm_password:
                    print("Error: Both --password and --confirm-password must be provided when using --user.")
                    return 1

                success, message = execute_password_reset(
                    args.user,
                    args.password,
                    args.confirm_password,
                    create_backup=not args.no_backup,
                    app=app,
                )
                if success:
                    print("\n" + "=" * 50)
                    print("PASSWORD RESET SUCCESSFUL")
                    print("=" * 50)
                    print(f"Username:            {message}")
                    print("Session status:      Previous sessions invalidated")
                    print("Storage security:    Hashed via Werkzeug (never stored in plaintext)")
                    print("=" * 50)
                    return 0
                else:
                    print(f"Error: {message}")
                    return 1

            return interactive_menu(app)


if __name__ == "__main__":
    sys.exit(main())
