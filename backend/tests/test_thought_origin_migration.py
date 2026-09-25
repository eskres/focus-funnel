"""The link from a thought to its proposal, and its migration (explore task 1.1)."""

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import NullPool

from app.db import create_engine
from app.models.thought import TagsType
from tests.test_provider_key_migration import run_alembic
from tests.test_proposal_migration import sqlite_columns
from tests.test_thought_migration import with_database

REVISION = "8a4d6f2b9c13"
PREVIOUS = "3f9d1b7e5a28"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
users = sa.table(
    "users", sa.column("id", sa.Uuid()), sa.column("issuer", sa.String()), sa.column("subject", sa.String())
)
conversations = sa.table(
    "conversations", sa.column("id", sa.Uuid()), sa.column("user_id", sa.Uuid()), sa.column("title", sa.Text())
)
proposals = sa.table(
    "proposals",
    sa.column("id", sa.Uuid()),
    sa.column("conversation_id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("position", sa.Integer()),
    sa.column("from_position", sa.Integer()),
    sa.column("to_position", sa.Integer()),
    sa.column("raw_text", sa.Text()),
    sa.column("parts", JSON),
)
thoughts = sa.table(
    "thoughts",
    sa.column("id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("title", sa.Text()),
    sa.column("summary", sa.Text()),
    sa.column("tags", TagsType),
)


def test_single_head_is_this_revision():
    res = run_alembic("sqlite+aiosqlite:///:memory:", "heads")
    assert res.returncode == 0, res.stderr
    heads = [line for line in res.stdout.splitlines() if line.strip()]
    assert heads == [f"{REVISION} (head)"]


def test_upgrade_and_downgrade_on_sqlite(tmp_path):
    db_file = tmp_path / "db.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    assert run_alembic(db_url, "upgrade", "head").returncode == 0
    assert "proposal_id" in sqlite_columns(db_file, "thoughts")

    res = run_alembic(db_url, "downgrade", "-1")
    assert res.returncode == 0, res.stderr
    assert "proposal_id" not in sqlite_columns(db_file, "thoughts")

    assert run_alembic(db_url, "upgrade", "head").returncode == 0
    res = run_alembic(db_url, "check")
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.postgres
def test_upgrade_and_downgrade_on_postgres():
    db_url, drop = with_database("ff_thought_origin_migration")
    try:
        for step in (("upgrade", "head"), ("check",), ("downgrade", "-1"), ("upgrade", "head")):
            res = run_alembic(db_url, *step)
            assert res.returncode == 0, res.stdout + res.stderr
    finally:
        drop()


def seed(db_url: str) -> dict[str, uuid.UUID]:
    """At the previous revision: one proposal with a saved part, a part whose
    thought is gone, and an unsaved part; a second proposal with two parts
    saved as one thought each; and a thought from no proposal."""
    ids = {name: uuid.uuid4() for name in ("user", "conv", "p1", "p2", "saved", "a", "b", "loose")}

    def part(thought_id):
        return {"title": "t", "summary": "s", "tags": [], "category": None, "thought_id": thought_id}

    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(users.insert().values(id=ids["user"], issuer="https://i", subject="alice"))
            await conn.execute(conversations.insert().values(id=ids["conv"], user_id=ids["user"], title="c"))
            for name in ("saved", "a", "b", "loose"):
                await conn.execute(
                    thoughts.insert().values(id=ids[name], user_id=ids["user"], title=name, summary="s", tags=[])
                )
            common = dict(
                conversation_id=ids["conv"], user_id=ids["user"], position=1,
                from_position=0, to_position=0, raw_text="r",
            )
            await conn.execute(proposals.insert().values(
                id=ids["p1"], **common,
                parts=[part(str(ids["saved"])), part(str(uuid.uuid4())), part(None)],
            ))
            await conn.execute(proposals.insert().values(
                id=ids["p2"], **common, parts=[part(str(ids["a"])), part(str(ids["b"]))],
            ))
        await engine.dispose()

    asyncio.run(main())
    return ids


def links(db_url: str) -> dict[uuid.UUID, uuid.UUID | None]:
    table = sa.table("thoughts", sa.column("id", sa.Uuid()), sa.column("proposal_id", sa.Uuid()))

    async def main():
        engine = create_engine(db_url, poolclass=NullPool)
        async with engine.connect() as conn:
            rows = (await conn.execute(sa.select(table.c.id, table.c.proposal_id))).all()
        await engine.dispose()
        return dict(rows)

    return asyncio.run(main())


def check_backfill(db_url: str):
    assert run_alembic(db_url, "upgrade", PREVIOUS).returncode == 0
    ids = seed(db_url)
    res = run_alembic(db_url, "upgrade", REVISION)
    assert res.returncode == 0, res.stderr
    assert links(db_url) == {
        ids["saved"]: ids["p1"],
        ids["a"]: ids["p2"],
        ids["b"]: ids["p2"],
        ids["loose"]: None,
    }


def test_backfill_links_saved_parts_on_sqlite(tmp_path):
    check_backfill(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}")


@pytest.mark.postgres
def test_backfill_links_saved_parts_on_postgres():
    db_url, drop = with_database("ff_thought_origin_backfill")
    try:
        check_backfill(db_url)
    finally:
        drop()
