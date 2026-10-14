"""Tests for the local user recovery utility (scripts/reset_users.py and reset_users.bat)."""

import os
import subprocess
import sys
from pathlib import Path
import pytest
from werkzeug.security import check_password_hash, generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from models import Category, Customer, Role, Supplier, User, db
from scripts.reset_users import (
    MIN_PASSWORD_LENGTH,
    create_pre_reset_backup,
    execute_password_reset,
    find_user_by_identifier,
    get_user_display_list,
    print_users_table,
    validate_password_policy,
)


@pytest.fixture
def recovery_app(tmp_path):
    """Fixture providing isolated application instance and database."""
    (tmp_path / "backups").mkdir(parents=True, exist_ok=True)
    (tmp_path / "backups-secondary").mkdir(parents=True, exist_ok=True)
    (tmp_path / "instance").mkdir(parents=True, exist_ok=True)
    (tmp_path / "static/uploads").mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "instance" / "store.db"
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "ROOT": tmp_path,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(db_path),
        }
    )

    with app.app_context():
        roles = [Role(name=n) for n in ["Admin", "Manager", "Cashier"]]
        db.session.add_all(roles)
        db.session.flush()

        for r in roles:
            db.session.add(
                User(
                    name=f"User {r.name}",
                    username=r.name.lower(),
                    password_hash=generate_password_hash("initial-password-123"),
                    role_id=r.id,
                    active=True,
                    version=1,
                )
            )

        db.session.add(Category(name="Default Category"))
        db.session.add(Supplier(name="Default Supplier"))
        db.session.add(Customer(name="Default Customer"))
        db.session.commit()

    return app


def test_list_users_does_not_expose_password_hashes(recovery_app, capsys):
    """Verify listing users outputs metadata without any password hashes."""
    with recovery_app.app_context():
        users = get_user_display_list()
        assert len(users) == 3

        for u in users:
            assert "password_hash" not in u
            assert "hash" not in u
            assert "initial-password-123" not in str(u)
            assert "scrypt:" not in str(u)
            assert "pbkdf2:" not in str(u)

        print_users_table(users)
        captured = capsys.readouterr().out
        assert "admin" in captured
        assert "manager" in captured
        assert "cashier" in captured
        assert "scrypt:" not in captured
        assert "pbkdf2:" not in captured
        assert "initial-password-123" not in captured


def test_find_user_by_id_and_username(recovery_app):
    """Verify lookup by integer ID, string ID, and case-insensitive username."""
    with recovery_app.app_context():
        u1 = find_user_by_identifier(1)
        assert u1 is not None
        assert u1.username == "admin"

        u1_str = find_user_by_identifier("1")
        assert u1_str is not None
        assert u1_str.username == "admin"

        u_case = find_user_by_identifier("ADMIN")
        assert u_case is not None
        assert u_case.id == 1

        u_manager = find_user_by_identifier("manager")
        assert u_manager is not None
        assert u_manager.role.name == "Manager"

        assert find_user_by_identifier("nonexistent") is None
        assert find_user_by_identifier(9999) is None
        assert find_user_by_identifier("") is None


def test_password_policy_and_mismatch_validation(recovery_app):
    """Verify StorePro's minimum password policy and confirmation matching."""
    with pytest.raises(ValueError, match="12 to 128 characters"):
        validate_password_policy("short")

    with pytest.raises(ValueError, match="12 to 128 characters"):
        validate_password_policy("a" * 129)

    validate_password_policy("valid-length-password-123")

    with recovery_app.app_context():
        ok, err = execute_password_reset("admin", "pass1", "pass2", create_backup=False)
        assert not ok
        assert "Passwords do not match" in err

        ok, err = execute_password_reset("admin", "short", "short", create_backup=False)
        assert not ok
        assert "12 to 128 characters" in err


def test_regression_exact_password_reset_and_reload(recovery_app):
    """Regression test ensuring password reset properly updates DB, refreshes session,
    validates the persisted hash, and enables normal login while invalidating old sessions.
    """
    with recovery_app.app_context():
        admin = User.query.filter_by(username="admin").one()
        admin_id = admin.id
        old_hash = admin.password_hash
        old_version = admin.version
        manager_hash = User.query.filter_by(username="manager").one().password_hash

        new_password = "RecoveredPassword123!"

        # Execute recovery reset with backup enabled
        success, message = execute_password_reset(
            user_identifier=admin_id,
            new_password=new_password,
            confirm_password=new_password,
            create_backup=True,
            app=recovery_app,
        )

        assert success is True
        assert message == "admin"

        # Explicitly expire session and reload user from database
        db.session.expire_all()
        persisted_admin = db.session.get(User, admin_id)

        assert persisted_admin is not None
        assert persisted_admin.password_hash != old_hash
        assert persisted_admin.password_hash != new_password
        assert new_password not in persisted_admin.password_hash

        # Verify persisted hash directly with Werkzeug check_password_hash
        assert check_password_hash(persisted_admin.password_hash, new_password) is True
        assert check_password_hash(persisted_admin.password_hash, "WrongPassword123!") is False

        # Session invalidation: version must be incremented
        assert persisted_admin.version == old_version + 1

        # Unrelated records must remain completely unchanged
        persisted_manager = User.query.filter_by(username="manager").one()
        assert persisted_manager.password_hash == manager_hash
        assert persisted_manager.version == 1

        # Verify normal /login authentication flow succeeds with new password
        client = recovery_app.test_client()
        login_res = client.post(
            "/login",
            data={"username": "admin", "password": new_password},
            follow_redirects=False,
        )
        assert login_res.status_code == 302
        assert login_res.headers.get("Location") in ("/", "/account")

        # Verify normal /login rejects wrong / old password
        client_wrong = recovery_app.test_client()
        login_wrong = client_wrong.post(
            "/login",
            data={"username": "admin", "password": "initial-password-123"},
        )
        assert login_wrong.status_code == 401


def test_rollback_on_failure(recovery_app, monkeypatch):
    """Verify database rollback occurs if an error happens during commit."""
    with recovery_app.app_context():
        admin = User.query.filter_by(username="admin").one()
        original_hash = admin.password_hash
        original_version = admin.version

        # Simulate database failure during commit
        def fail_commit():
            raise RuntimeError("Simulated SQLite write error")

        monkeypatch.setattr(db.session, "commit", fail_commit)

        ok, err = execute_password_reset(
            "admin",
            "ValidNewPassword123!",
            "ValidNewPassword123!",
            create_backup=False,
            app=recovery_app,
        )

        assert ok is False
        assert "Database transaction failed" in err

        # Reload after rollback
        db.session.expire_all()
        admin_after = User.query.filter_by(username="admin").one()
        assert admin_after.password_hash == original_hash
        assert admin_after.version == original_version


def test_safety_backup_creation(recovery_app):
    """Verify safety SQLite backup is generated prior to modification."""
    with recovery_app.app_context():
        bak_path = create_pre_reset_backup(recovery_app)
        assert bak_path is not None
        assert Path(bak_path).exists()
        assert Path(bak_path).stat().st_size > 0
        assert "pre_reset" in Path(bak_path).name


def test_reset_users_bat_execution(tmp_path):
    """Verify reset_users.bat works from command prompt without errors or hash leaks."""
    import shutil

    project_root = Path(__file__).resolve().parents[1]
    bat_file = project_root / "reset_users.bat"
    assert bat_file.exists(), "reset_users.bat does not exist at project root"

    # Starting StorePro upgrades its database, so the utility lists the users
    # of a private copy (plain file reads) instead of opening the real store.
    live = project_root / "instance" / "store.db"
    copy = tmp_path / "store.db"
    for suffix in ("", "-wal"):
        if Path(str(live) + suffix).exists():
            shutil.copyfile(str(live) + suffix, str(copy) + suffix)
    env = {**os.environ, "STOREPRO_DATABASE_URI": "sqlite:///" + str(copy)}

    # Run reset_users.bat --list through cmd.exe with null input (satisfying pause)
    res = subprocess.run(
        ["cmd.exe", "/c", "reset_users.bat --list < nul"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        env=env,
    )

    assert res.returncode == 0
    assert "Existing StorePro Users" in res.stdout
    assert "george" in res.stdout
    assert "scrypt:" not in res.stdout
    assert "pbkdf2:" not in res.stdout
