"""The connector tables and their migration (mcp-connectors task 3.1)."""

import pytest

from tests.test_proposal_migration import sqlite_columns, sqlite_tables
from tests.test_provider_key_migration import run_alembic
from tests.test_thought_migration import with_database

REVISION = "9b4660dc0603"
PREVIOUS = "0162bb890895"
TABLES = {"connectors", "conversation_connectors", "tool_actions"}


def test_this_revision_is_below_the_single_head():
    # Later revisions exist, so these tests downgrade to PREVIOUS, not "-1".
    res = run_alembic("sqlite+aiosqlite:///:memory:", "heads")
    assert res.returncode == 0, res.stderr
    heads = [line.split()[0] for line in res.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, res.stdout
    res = run_alembic("sqlite+aiosqlite:///:memory:", "history", "-r", f"{REVISION}:{heads[0]}")
    assert res.returncode == 0, res.stderr
    assert f"{PREVIOUS} -> {REVISION}" in res.stdout


def test_upgrade_and_downgrade_on_sqlite(tmp_path):
    db_file = tmp_path / "db.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr
    assert TABLES <= sqlite_tables(db_file)
    assert "connector_warning_accepted_at" in sqlite_columns(db_file, "users")
    assert "auth_ciphertext" in sqlite_columns(db_file, "connectors")

    res = run_alembic(db_url, "downgrade", PREVIOUS)
    assert res.returncode == 0, res.stderr
    assert not TABLES & sqlite_tables(db_file)
    assert "connector_warning_accepted_at" not in sqlite_columns(db_file, "users")

    assert run_alembic(db_url, "upgrade", "head").returncode == 0
    res = run_alembic(db_url, "check")
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.postgres
def test_upgrade_and_downgrade_on_postgres():
    # A name of its own: other suites create and drop their sibling databases.
    db_url, drop = with_database("ff07_mcp_connectors_migration")
    try:
        steps = (("upgrade", "head"), ("check",), ("downgrade", PREVIOUS), ("upgrade", "head"), ("check",))
        for step in steps:
            res = run_alembic(db_url, *step)
            assert res.returncode == 0, (step, res.stdout + res.stderr)
    finally:
        drop()
