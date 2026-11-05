"""A thought's date columns and their migration (thought-dates task 1.1)."""

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from app.db import create_engine
from app.models.thought import TagsType
from tests.test_proposal_migration import sqlite_columns
from tests.test_provider_key_migration import run_alembic
from tests.test_thought_migration import with_database

REVISION = "8de09c18db91"
PREVIOUS = "8a4d6f2b9c13"
COLUMNS = {"starts_on", "starts_at", "ends_on", "ends_at", "time_zone"}
INDEX = "ix_thoughts_user_id_starts_on"

users = sa.table(
    "users", sa.column("id", sa.Uuid()), sa.column("issuer", sa.String()), sa.column("subject", sa.String())
)
thoughts = sa.table(
    "thoughts",
    sa.column("id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("title", sa.Text()),
    sa.column("summary", sa.Text()),
    sa.column("tags", TagsType),
)
dates = sa.table("thoughts", sa.column("id", sa.Uuid()), *(sa.column(name) for name in sorted(COLUMNS)))


def test_this_revision_is_below_the_single_head():
    # Later revisions may exist, so these tests downgrade to PREVIOUS, not "-1".
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
    assert run_alembic(db_url, "upgrade", "head").returncode == 0
    assert COLUMNS <= sqlite_columns(db_file, "thoughts")

    res = run_alembic(db_url, "downgrade", PREVIOUS)
    assert res.returncode == 0, res.stderr
    assert not COLUMNS & sqlite_columns(db_file, "thoughts")

    assert run_alembic(db_url, "upgrade", "head").returncode == 0
    res = run_alembic(db_url, "check")
    assert res.returncode == 0, res.stdout + res.stderr


def postgres_shape(db_url: str) -> tuple[set[str], str | None]:
    """The thoughts columns and the date index's definition, if any."""

    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        async with engine.connect() as conn:
            columns = set(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT column_name FROM information_schema.columns"
                            " WHERE table_name = 'thoughts'"
                        )
                    )
                ).scalars()
            )
            index = (
                await conn.execute(
                    sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
                    {"name": INDEX},
                )
            ).scalar_one_or_none()
        await engine.dispose()
        return columns, index

    return asyncio.run(main())


@pytest.mark.postgres
def test_upgrade_and_downgrade_on_postgres():
    # A name of its own: other suites create and drop their sibling databases.
    db_url, drop = with_database("ff05_thought_dates_migration")
    try:
        for step in (("upgrade", "head"), ("check",)):
            res = run_alembic(db_url, *step)
            assert res.returncode == 0, (step, res.stdout + res.stderr)
        columns, index = postgres_shape(db_url)
        assert COLUMNS <= columns
        assert index is not None and "(user_id, starts_on)" in index
        assert "WHERE (starts_on IS NOT NULL)" in index

        res = run_alembic(db_url, "downgrade", PREVIOUS)
        assert res.returncode == 0, res.stdout + res.stderr
        columns, index = postgres_shape(db_url)
        assert not COLUMNS & columns
        assert index is None

        for step in (("upgrade", "head"), ("check",)):
            res = run_alembic(db_url, *step)
            assert res.returncode == 0, (step, res.stdout + res.stderr)
    finally:
        drop()


def seed(db_url: str) -> uuid.UUID:
    """At the previous revision: one user with one thought."""
    user_id, thought_id = uuid.uuid4(), uuid.uuid4()

    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(users.insert().values(id=user_id, issuer="https://i", subject="alice"))
            await conn.execute(
                thoughts.insert().values(id=thought_id, user_id=user_id, title="t", summary="s", tags=[])
            )
        await engine.dispose()

    asyncio.run(main())
    return thought_id


def stored_dates(db_url: str) -> dict[uuid.UUID, dict]:
    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        async with engine.connect() as conn:
            rows = (await conn.execute(sa.select(dates))).mappings().all()
        await engine.dispose()
        return {row["id"]: {name: row[name] for name in COLUMNS} for row in rows}

    return asyncio.run(main())


def check_no_dates(db_url: str):
    assert run_alembic(db_url, "upgrade", PREVIOUS).returncode == 0
    thought_id = seed(db_url)
    res = run_alembic(db_url, "upgrade", REVISION)
    assert res.returncode == 0, res.stderr
    assert stored_dates(db_url) == {thought_id: dict.fromkeys(COLUMNS)}


def test_existing_thoughts_have_no_date_on_sqlite(tmp_path):
    check_no_dates(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}")


@pytest.mark.postgres
def test_existing_thoughts_have_no_date_on_postgres():
    db_url, drop = with_database("ff05_thought_dates_existing")
    try:
        check_no_dates(db_url)
    finally:
        drop()
