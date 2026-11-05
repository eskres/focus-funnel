"""The setup_state table and its row (self-hosting-setup task 2.2)."""

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from app.db import create_engine
from tests.test_provider_key_migration import run_alembic
from tests.test_thought_migration import with_database

REVISION = "4d7a1c9e2b60"
PREVIOUS = "9b4660dc0603"

users = sa.table(
    "users", sa.column("id", sa.Uuid()), sa.column("issuer", sa.String()), sa.column("subject", sa.String())
)
setup_state = sa.table(
    "setup_state",
    sa.column("id", sa.Integer()),
    sa.column("token_hash", sa.String()),
    sa.column("token_created_at", sa.DateTime(timezone=True)),
    sa.column("completed_at", sa.DateTime(timezone=True)),
)


def alembic_ok(db_url: str, *args: str) -> str:
    res = run_alembic(db_url, *args)
    assert res.returncode == 0, (args, res.stdout + res.stderr)
    return res.stdout


def test_single_head_follows_this_revision():
    out = alembic_ok("sqlite+aiosqlite:///:memory:", "heads")
    heads = [line.split()[0] for line in out.splitlines() if line.strip()]
    assert len(heads) == 1, out
    out = alembic_ok("sqlite+aiosqlite:///:memory:", "history", "-r", f"{PREVIOUS}:{heads[0]}")
    assert f"{PREVIOUS} -> {REVISION}" in out


def run(db_url: str, work):
    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                return await work(conn)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def rows(conn):
    return (await conn.execute(sa.select(setup_state))).all()


async def has_table(conn) -> bool:
    return await conn.run_sync(lambda sync: sa.inspect(sync).has_table("setup_state"))


async def add_user(conn):
    await conn.execute(users.insert().values(id=uuid.uuid4(), issuer="https://i", subject="ana"))


def check_round_trip(db_url: str):
    for step in (("upgrade", "head"), ("check",), ("downgrade", "-1"), ("upgrade", "head"), ("check",)):
        alembic_ok(db_url, *step)


def check_empty_database(db_url: str):
    alembic_ok(db_url, "upgrade", REVISION)
    [row] = run(db_url, rows)
    assert row.id == 1
    assert row.token_hash is None
    assert row.token_created_at is None
    assert row.completed_at is None


def check_install_in_use(db_url: str):
    alembic_ok(db_url, "upgrade", PREVIOUS)
    run(db_url, add_user)
    # A user, but no chat_models row: still counts as set up.
    assert run(db_url, lambda conn: _count(conn, "chat_models")) == 0
    alembic_ok(db_url, "upgrade", REVISION)
    [row] = run(db_url, rows)
    assert row.id == 1
    assert row.token_hash is None
    assert row.completed_at is not None


async def _count(conn, table: str) -> int:
    return (await conn.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one()


def check_downgrade_drops_the_table(db_url: str):
    alembic_ok(db_url, "upgrade", REVISION)
    assert run(db_url, has_table)
    alembic_ok(db_url, "downgrade", PREVIOUS)
    assert not run(db_url, has_table)


def sqlite_url(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}"


def test_round_trip_and_check_on_sqlite(tmp_path):
    check_round_trip(sqlite_url(tmp_path))


def test_empty_database_gets_an_open_row_on_sqlite(tmp_path):
    check_empty_database(sqlite_url(tmp_path))


def test_install_in_use_is_finished_on_sqlite(tmp_path):
    check_install_in_use(sqlite_url(tmp_path))


def test_downgrade_drops_the_table_on_sqlite(tmp_path):
    check_downgrade_drops_the_table(sqlite_url(tmp_path))


@pytest.mark.postgres
@pytest.mark.parametrize(
    "name, check",
    [
        ("ff08_setup_state_round_trip", check_round_trip),
        ("ff08_setup_state_empty", check_empty_database),
        ("ff08_setup_state_in_use", check_install_in_use),
        ("ff08_setup_state_downgrade", check_downgrade_drops_the_table),
    ],
)
def test_on_postgres(name, check):
    db_url, drop = with_database(name)
    try:
        check(db_url)
    finally:
        drop()
