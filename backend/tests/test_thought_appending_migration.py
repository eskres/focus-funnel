"""thought_additions and the similarity baseline columns (thought-appending task 1.1)."""

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from app.db import create_engine
from tests.test_proposal_migration import sqlite_columns, sqlite_tables
from tests.test_provider_key_migration import run_alembic
from tests.test_thought_migration import with_database

REVISION = "0162bb890895"
PREVIOUS = "8de09c18db91"
BASELINE_COLUMNS = {"similarity_p95", "similarity_p99", "baseline_thoughts"}
ADDITION_COLUMNS = {
    "id", "thought_id", "user_id", "proposal_id", "from_position", "to_position",
    "added_at", "after_updated_at", "before", "undone_at",
}


def test_single_head_is_this_revision():
    res = run_alembic("sqlite+aiosqlite:///:memory:", "heads")
    assert res.returncode == 0, res.stderr
    heads = [line for line in res.stdout.splitlines() if line.strip()]
    assert heads == [f"{REVISION} (head)"]
    res = run_alembic("sqlite+aiosqlite:///:memory:", "history", "-r", f"{PREVIOUS}:{REVISION}")
    assert res.returncode == 0, res.stderr
    assert f"{PREVIOUS} -> {REVISION}" in res.stdout


def test_upgrade_and_downgrade_on_sqlite(tmp_path):
    db_file = tmp_path / "db.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stdout + res.stderr
    assert sqlite_columns(db_file, "thought_additions") == ADDITION_COLUMNS
    assert BASELINE_COLUMNS <= sqlite_columns(db_file, "search_indexes")

    res = run_alembic(db_url, "downgrade", "-1")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "thought_additions" not in sqlite_tables(db_file)
    assert not BASELINE_COLUMNS & sqlite_columns(db_file, "search_indexes")

    for step in (("upgrade", "head"), ("check",)):
        res = run_alembic(db_url, *step)
        assert res.returncode == 0, (step, res.stdout + res.stderr)


def postgres_shape(db_url: str) -> tuple[set[str], set[str], set[str]]:
    """The columns of thought_additions and search_indexes, and the indexes
    on thought_additions."""

    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        async with engine.connect() as conn:
            def columns(table):
                return {
                    row[0] for row in conn.sync_connection.execute(sa.text(
                        "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
                    ), {"t": table})
                }

            additions = await conn.run_sync(lambda _: columns("thought_additions"))
            indexes = await conn.run_sync(lambda _: columns("search_indexes"))
            names = set((await conn.execute(sa.text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'thought_additions'"
            ))).scalars())
        await engine.dispose()
        return additions, indexes, names

    return asyncio.run(main())


@pytest.mark.postgres
def test_upgrade_and_downgrade_on_postgres():
    # A name of its own: other suites create and drop their sibling databases.
    db_url, drop = with_database("ff_thought_appending_migration")
    try:
        res = run_alembic(db_url, "upgrade", "head")
        assert res.returncode == 0, res.stdout + res.stderr
        additions, indexes, names = postgres_shape(db_url)
        assert additions == ADDITION_COLUMNS
        assert BASELINE_COLUMNS <= indexes
        assert "ix_thought_additions_thought_id" in names

        res = run_alembic(db_url, "downgrade", "-1")
        assert res.returncode == 0, res.stdout + res.stderr
        additions, indexes, _ = postgres_shape(db_url)
        assert additions == set()
        assert not BASELINE_COLUMNS & indexes

        for step in (("upgrade", "head"), ("check",)):
            res = run_alembic(db_url, *step)
            assert res.returncode == 0, (step, res.stdout + res.stderr)
    finally:
        drop()
