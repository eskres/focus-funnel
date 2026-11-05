"""Deleting the added event categories, now a fixed kind (event-category task 1.1)."""

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from app.db import create_engine
from app.models.thought import TagsType
from tests.test_provider_key_migration import run_alembic
from tests.test_thought_migration import with_database

REVISION = "2bea7235fdf6"
PREVIOUS = "8a4d6f2b9c13"

users = sa.table(
    "users", sa.column("id", sa.Uuid()), sa.column("issuer", sa.String()), sa.column("subject", sa.String())
)
user_categories = sa.table(
    "user_categories", sa.column("id", sa.Uuid()), sa.column("user_id", sa.Uuid()), sa.column("name", sa.Text())
)
thoughts = sa.table(
    "thoughts",
    sa.column("id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("title", sa.Text()),
    sa.column("summary", sa.Text()),
    sa.column("tags", TagsType),
    sa.column("category", sa.Text()),
)


def test_single_head_follows_this_revision():
    res = run_alembic("sqlite+aiosqlite:///:memory:", "heads")
    assert res.returncode == 0, res.stderr
    heads = [line.split()[0] for line in res.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, res.stdout
    res = run_alembic("sqlite+aiosqlite:///:memory:", "history", "-r", f"{PREVIOUS}:{heads[0]}")
    assert res.returncode == 0, res.stderr
    assert f"{PREVIOUS} -> {REVISION}" in res.stdout


def test_upgrade_and_downgrade_on_sqlite(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}"
    for step in (("upgrade", "head"), ("downgrade", "-1"), ("upgrade", "head"), ("check",)):
        res = run_alembic(db_url, *step)
        assert res.returncode == 0, (step, res.stdout + res.stderr)


@pytest.mark.postgres
def test_upgrade_and_downgrade_on_postgres():
    # A name of its own: other suites create and drop their sibling databases.
    db_url, drop = with_database("ff04_event_category_migration")
    try:
        for step in (("upgrade", "head"), ("downgrade", "-1"), ("upgrade", "head"), ("check",)):
            res = run_alembic(db_url, *step)
            assert res.returncode == 0, (step, res.stdout + res.stderr)
    finally:
        drop()


def seed(db_url: str) -> dict[str, uuid.UUID]:
    """At the previous revision: alice added event and recipe and filed a
    thought as event; bob added event and travel."""
    ids = {name: uuid.uuid4() for name in ("alice", "bob", "thought")}

    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            for name in ("alice", "bob"):
                await conn.execute(users.insert().values(id=ids[name], issuer="https://i", subject=name))
            for user, name in (("alice", "event"), ("alice", "recipe"), ("bob", "event"), ("bob", "travel")):
                await conn.execute(user_categories.insert().values(id=uuid.uuid4(), user_id=ids[user], name=name))
            await conn.execute(thoughts.insert().values(
                id=ids["thought"], user_id=ids["alice"], title="dinner", summary="s", tags=[], category="event",
            ))
        await engine.dispose()

    asyncio.run(main())
    return ids


def stored(db_url: str):
    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        async with engine.connect() as conn:
            rows = (await conn.execute(sa.select(user_categories.c.user_id, user_categories.c.name))).all()
            categories = (await conn.execute(sa.select(thoughts.c.id, thoughts.c.category))).all()
        await engine.dispose()
        return {tuple(row) for row in rows}, dict(categories)

    return asyncio.run(main())


def check_delete(db_url: str):
    res = run_alembic(db_url, "upgrade", PREVIOUS)
    assert res.returncode == 0, res.stderr
    ids = seed(db_url)
    res = run_alembic(db_url, "upgrade", REVISION)
    assert res.returncode == 0, res.stderr
    rows, categories = stored(db_url)
    assert rows == {(ids["alice"], "recipe"), (ids["bob"], "travel")}
    assert categories == {ids["thought"]: "event"}


def test_upgrade_deletes_added_event_only_on_sqlite(tmp_path):
    check_delete(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}")


@pytest.mark.postgres
def test_upgrade_deletes_added_event_only_on_postgres():
    db_url, drop = with_database("ff04_event_category_delete")
    try:
        check_delete(db_url)
    finally:
        drop()
