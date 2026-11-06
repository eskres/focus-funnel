"""The spend cap columns on user_settings and their migration (stop-and-spend-cap task 1.1)."""

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from app.db import create_engine
from tests.test_setup_state_migration import alembic_ok
from tests.test_thought_migration import with_database

REVISION = "460c92991076"
PREVIOUS = "f160f49f7141"
CAP_COLUMNS = {"cap_unit", "cap_amount"}

users = sa.table(
    "users", sa.column("id", sa.Uuid()), sa.column("issuer", sa.String()), sa.column("subject", sa.String())
)
user_settings = sa.table(
    "user_settings",
    sa.column("user_id", sa.Uuid()),
    sa.column("temperature", sa.Float()),
    sa.column("warning_unit", sa.String()),
    sa.column("warning_amount", sa.Numeric(18, 6)),
)
caps = sa.table(
    "user_settings",
    sa.column("user_id", sa.Uuid()),
    sa.column("cap_unit", sa.String()),
    sa.column("cap_amount", sa.Numeric(18, 6)),
)


def test_the_single_head_is_this_revision():
    out = alembic_ok("sqlite+aiosqlite:///:memory:", "heads")
    heads = [line.split()[0] for line in out.splitlines() if line.strip()]
    assert heads == [REVISION], out
    out = alembic_ok("sqlite+aiosqlite:///:memory:", "history", "-r", f"{PREVIOUS}:{REVISION}")
    assert f"{PREVIOUS} -> {REVISION} (head)" in out


def run(db_url: str, work):
    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                return await work(conn)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def columns(conn) -> dict[str, dict]:
    found = await conn.run_sync(lambda sync: sa.inspect(sync).get_columns("user_settings"))
    return {column["name"]: column for column in found}


def check_upgrade_and_downgrade(db_url: str):
    user_id = uuid.uuid4()

    async def add(conn):
        await conn.execute(users.insert().values(id=user_id, issuer="https://i", subject="ana"))
        await conn.execute(
            user_settings.insert().values(
                user_id=user_id, temperature=0.4, warning_unit="usd", warning_amount=3
            )
        )

    async def read(conn):
        row = (await conn.execute(sa.select(caps).where(caps.c.user_id == user_id))).one()
        return await columns(conn), row

    alembic_ok(db_url, "upgrade", PREVIOUS)
    run(db_url, add)
    assert not CAP_COLUMNS & set(run(db_url, columns))

    alembic_ok(db_url, "upgrade", REVISION)
    found, row = run(db_url, read)
    assert CAP_COLUMNS <= set(found)
    assert found["cap_unit"]["nullable"] and found["cap_amount"]["nullable"]
    assert isinstance(found["cap_unit"]["type"], sa.String)
    assert found["cap_unit"]["type"].length == 8
    assert isinstance(found["cap_amount"]["type"], sa.Numeric)
    assert (found["cap_amount"]["type"].precision, found["cap_amount"]["type"].scale) == (18, 6)
    assert (row.cap_unit, row.cap_amount) == (None, None)
    alembic_ok(db_url, "check")

    alembic_ok(db_url, "downgrade", PREVIOUS)
    kept = run(db_url, columns)
    assert not CAP_COLUMNS & set(kept)
    assert {"temperature", "warning_unit", "warning_amount"} <= set(kept)

    alembic_ok(db_url, "upgrade", "head")
    alembic_ok(db_url, "check")


def test_upgrade_and_downgrade_on_sqlite(tmp_path):
    check_upgrade_and_downgrade(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}")


@pytest.mark.postgres
def test_upgrade_and_downgrade_on_postgres():
    # A name of its own: other suites create and drop their sibling databases.
    db_url, drop = with_database("ff_f2_spend_cap_migration")
    try:
        check_upgrade_and_downgrade(db_url)
    finally:
        drop()
