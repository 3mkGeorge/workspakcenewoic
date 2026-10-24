"""Suite-wide guard: tests never open the StorePro working database.

Starting the app runs schema upgrades, so a test that reaches the real store
database would migrate it. Every test uses its own temporary database. This
module makes that a guarantee instead of a convention:

* the working database (instance/store.db of this checkout, and any database
  already named by STOREPRO_DATABASE_URI) is recorded before tests run;
* STOREPRO_DATABASE_URI is pointed at a throwaway file, so an app started with
  default settings (in this process or in a subprocess) lands there;
* an audit hook refuses SQLite connections and file writes to the working
  database, and the test that tried fails.

Reading the file (to make a private copy) stays allowed.
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKING_DATABASE = PROJECT_ROOT / "instance" / "store.db"


def _sqlite_path(uri):
    if uri and uri.startswith("sqlite:///"):
        return uri[len("sqlite:///"):]
    return None


_protected_files = {os.path.realpath(WORKING_DATABASE)}
_configured = _sqlite_path(os.environ.get("STOREPRO_DATABASE_URI"))
if _configured:
    _protected_files.add(os.path.realpath(_configured))
_protected = {path + suffix for path in _protected_files for suffix in ("", "-wal", "-shm", "-journal")}
_names = {os.path.basename(path) for path in _protected}
VIOLATIONS = []

_scratch = tempfile.mkdtemp(prefix="storepro-tests-")
atexit.register(shutil.rmtree, _scratch, True)
os.environ["STOREPRO_DATABASE_URI"] = "sqlite:///" + os.path.join(_scratch, "default.db")

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _target(event, args):
    if event == "sqlite3.connect":
        database = args[0]
        if isinstance(database, (bytes, os.PathLike)):
            database = os.fsdecode(database)
        if isinstance(database, str) and database.startswith("file:"):
            database = database[5:].split("?", 1)[0]
        return database
    if event == "open" and not isinstance(args[0], int):
        mode, flags = args[1], args[2]
        writing = any(c in mode for c in "wax+") if isinstance(mode, str) else bool((flags or 0) & _WRITE_FLAGS)
        return os.fsdecode(args[0]) if writing else None
    return None


def _guard(event, args):
    if event not in ("sqlite3.connect", "open"):
        return
    path = _target(event, args)
    if not path or os.path.basename(path) not in _names:
        return
    if os.path.realpath(path) in _protected:
        VIOLATIONS.append(path)
        raise RuntimeError(f"Tests must not open the StorePro working database ({path}); use a temporary copy.")


sys.addaudithook(_guard)


@pytest.fixture(autouse=True)
def _working_database_untouched():
    start = len(VIOLATIONS)
    yield
    attempts = VIOLATIONS[start:]
    del VIOLATIONS[start:]
    assert not attempts, f"Test tried to open the StorePro working database: {attempts}"
