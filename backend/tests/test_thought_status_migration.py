"""A thought's status columns and their migration (thought-status task 1.1)."""

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from app.db import create_engine
from app.models import Thought
from app.models.thought import TagsType
from tests.test_setup_state_migration import alembic_ok
from tests.test_thought_migration import with_database

REVISION = "f160f49f7141"
PREVIOUS = "4d7a1c9e2b60"
CONSTRAINT = "ck_thoughts_status"

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
status = sa.table(
    "thoughts",
    sa.column("id", sa.Uuid()),
    sa.column("status", sa.Text()),
    sa.column("status_changed_at", sa.DateTime(timezone=True)),
)


def test_this_revision_is_below_the_single_head():
    # Later revisions exist (the head test is in test_spend_cap_migration.py),
    # so these tests downgrade to PREVIOUS, not "-1".
    out = alembic_ok("sqlite+aiosqlite:///:memory:", "heads")
    heads = [line.split()[0] for line in out.splitlines() if line.strip()]
    assert len(heads) == 1, out
    out = alembic_ok("sqlite+aiosqlite:///:memory:", "history", "-r", f"{REVISION}:{heads[0]}")
    assert f"{PREVIOUS} -> {REVISION}" in out


def test_the_model_names_the_check_constraint():
    names = {
        constraint.name
        for constraint in Thought.__table__.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert names == {CONSTRAINT}


def run(db_url: str, work):
    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                return await work(conn)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def check_round_trip(db_url: str):
    for step in (("upgrade", "head"), ("check",), ("downgrade", PREVIOUS), ("upgrade", "head"), ("check",)):
        alembic_ok(db_url, *step)


def check_old_thoughts_become_open(db_url: str):
    user_id, thought_id = uuid.uuid4(), uuid.uuid4()

    async def add(conn):
        await conn.execute(users.insert().values(id=user_id, issuer="https://i", subject="ana"))
        await conn.execute(
            thoughts.insert().values(
                id=thought_id, user_id=user_id, title="Call the plumber", summary="s", tags=["home"]
            )
        )

    async def read(conn):
        return (await conn.execute(sa.select(status).where(status.c.id == thought_id))).one()

    alembic_ok(db_url, "upgrade", PREVIOUS)
    run(db_url, add)
    alembic_ok(db_url, "upgrade", REVISION)
    row = run(db_url, read)
    assert row.status == "open"
    assert row.status_changed_at is None


def check_archived_is_refused(db_url: str):
    alembic_ok(db_url, "upgrade", "head")
    user_id = uuid.uuid4()

    async def add(conn):
        await conn.execute(users.insert().values(id=user_id, issuer="https://i", subject="ana"))
        with_status = sa.table(
            "thoughts", *(sa.column(c.name, c.type) for c in thoughts.c), sa.column("status", sa.Text())
        )
        await conn.execute(
            with_status.insert().values(
                id=uuid.uuid4(), user_id=user_id, title="t", summary="s", tags=[], status="archived"
            )
        )

    with pytest.raises(IntegrityError) as raised:
        run(db_url, add)
    assert CONSTRAINT in str(raised.value)


def sqlite_url(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}"


def test_round_trip_and_check_on_sqlite(tmp_path):
    check_round_trip(sqlite_url(tmp_path))


def test_an_old_thought_becomes_open_on_sqlite(tmp_path):
    check_old_thoughts_become_open(sqlite_url(tmp_path))


def test_archived_is_refused_on_sqlite(tmp_path):
    check_archived_is_refused(sqlite_url(tmp_path))


@pytest.mark.postgres
@pytest.mark.parametrize(
    "name, check",
    [
        # Names of their own: other suites create and drop their sibling databases.
        ("ff_thought_status_migration", check_round_trip),
        ("ff_thought_status_migration_old", check_old_thoughts_become_open),
        ("ff_thought_status_migration_archived", check_archived_is_refused),
    ],
)
def test_on_postgres(name, check):
    db_url, drop = with_database(name)
    try:
        check(db_url)
    finally:
        drop()
