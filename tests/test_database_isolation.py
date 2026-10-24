"""The test suite cannot open the StorePro working database (guard in conftest.py).

These checks never write to the real file: the write case calls the guard
directly, and the connection attempt is read-only and immutable.
"""

import os
import sqlite3

import pytest

import conftest


def test_default_database_points_to_a_throwaway_file():
    uri = os.environ["STOREPRO_DATABASE_URI"]
    assert uri.startswith("sqlite:///")
    assert os.path.realpath(uri[len("sqlite:///"):]) != os.path.realpath(conftest.WORKING_DATABASE)


def test_app_started_with_default_settings_uses_the_throwaway_database():
    from app import create_app

    app = create_app({"TESTING": True})
    assert app.config["SQLALCHEMY_DATABASE_URI"] == os.environ["STOREPRO_DATABASE_URI"]


def test_working_database_connections_and_writes_are_refused():
    live = str(conftest.WORKING_DATABASE)
    with pytest.raises(RuntimeError, match="working database"):
        sqlite3.connect(f"file:{live}?mode=ro&immutable=1", uri=True)
    for event, args in (
        ("sqlite3.connect", (live,)),
        ("open", (live + "-wal", "ab", os.O_WRONLY | os.O_APPEND)),
        ("open", (live, None, os.O_RDWR)),
    ):
        with pytest.raises(RuntimeError):
            conftest._guard(event, args)
    conftest._guard("open", (live, "rb", os.O_RDONLY))  # reading for a private copy is allowed
    conftest.VIOLATIONS.clear()  # the refusals above were expected
