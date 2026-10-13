"""StorePro startup identity, directory validation, and asset versioning."""

import os
import sys
from pathlib import Path
from flask import current_app

STOREPRO_VERSION = "1.0.0"

# Files that must exist in a valid StorePro project root
REQUIRED_PROJECT_FILES = (
    "app.py",
    "templates/base.html",
    "static/css/app.css",
    "static/css/pos.css",
    "models/__init__.py",
    "requirements-lock.txt",
)


def get_app_version() -> str:
    """Return the canonical StorePro application version."""
    return STOREPRO_VERSION


def get_asset_version(filename: str = None) -> str:
    """Return a deterministic version string for static assets.

    Combines application version with asset file modification time when available,
    ensuring browsers automatically revalidate assets after modifications or releases.
    """
    base = get_app_version()
    if not filename:
        return base
    try:
        # Determine static folder from current app or relative to this service
        static_dir = Path(current_app.static_folder) if current_app else Path(__file__).resolve().parents[1] / "static"
        asset_path = static_dir / filename
        if asset_path.exists():
            mtime = int(asset_path.stat().st_mtime)
            return f"{base}.{mtime}"
    except Exception:
        pass
    return base


def validate_startup_directory(path=None) -> Path:
    """Validate that StorePro is executing from an expected, valid project root.

    Raises RuntimeError with a clear message if executed from an unexpected
    or incomplete directory (e.g. an unverified Desktop or Downloads copy).
    """
    target = Path(path or Path.cwd()).resolve()

    # 1. Verify existence of required project files
    for rel_file in REQUIRED_PROJECT_FILES:
        expected_file = target / rel_file
        if not expected_file.exists():
            raise RuntimeError(
                f"StorePro startup directory validation failed: '{target}' is missing required file '{rel_file}'. "
                f"Ensure you are running StorePro from its canonical project root."
            )

    # 2. Prevent accidental execution from an unverified Desktop or Downloads copy
    if not os.environ.get("STOREPRO_ALLOW_DESKTOP_BUILD"):
        normalized = str(target).lower()
        if normalized.endswith(r"\desktop\store-app") or normalized.endswith(r"/desktop/store-app") or \
           normalized.endswith(r"\downloads\store-app") or normalized.endswith(r"/downloads/store-app"):
            raise RuntimeError(
                f"StorePro startup rejected: '{target}' is an unverified Desktop or Downloads copy. "
                f"Please launch StorePro from the canonical project installation."
            )

    # 3. Explicit canonical directory check if configured in environment
    expected_canonical = os.environ.get("STOREPRO_CANONICAL_DIR")
    if expected_canonical:
        canonical_path = Path(expected_canonical).resolve()
        if target != canonical_path:
            raise RuntimeError(
                f"StorePro startup directory mismatch: executed from '{target}', "
                f"expected canonical directory '{canonical_path}'."
            )

    return target


def get_startup_identity(app, host: str = None, port: int = None) -> dict:
    """Collect startup identity metadata for logging and programmatic verification."""
    h = host or os.environ.get("STOREPRO_HOST", "127.0.0.1")
    p = port or int(os.environ.get("STOREPRO_PORT", "5000"))
    root_path = Path(app.config.get("ROOT", Path(__file__).resolve().parents[1])).resolve()
    
    db_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if db_uri.startswith("sqlite:///"):
        db_path = str(Path(db_uri.replace("sqlite:///", "")).resolve())
    else:
        db_path = db_uri

    return {
        "project_root": str(root_path),
        "version": get_app_version(),
        "database_path": db_path,
        "host": h,
        "port": p,
        "url": f"http://{h}:{p}",
    }


def print_startup_banner(app, host: str = None, port: int = None) -> None:
    """Print clear startup identity details to the operator console."""
    info = get_startup_identity(app, host=host, port=port)
    print("=" * 70, flush=True)
    print(f" StorePro Local Store Management - v{info['version']}", flush=True)
    print("=" * 70, flush=True)
    print(f" Project Root : {info['project_root']}", flush=True)
    print(f" Version      : {info['version']}", flush=True)
    print(f" Database     : {info['database_path']}", flush=True)
    print(f" Listening At : {info['url']}", flush=True)
    print("=" * 70, flush=True)
    print(f"StorePro is running at {info['url']}. Keep this window open.", flush=True)
