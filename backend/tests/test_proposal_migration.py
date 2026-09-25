"""The proposal and category tables and their migration (push-and-pull task 1.1)."""

import asyncio
import sqlite3
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import get_or_create_user
from app.db import create_engine
from app.models import Conversation, Proposal, User, UserCategory
from tests.conftest import TEST_ISSUER
from tests.test_provider_key_migration import run_alembic
from tests.test_thought_migration import with_database

REVISION = "3f9d1b7e5a28"
PREVIOUS = "5e8b2c0d4a17"
TABLES = {"proposals", "user_categories"}


def test_single_head_is_this_revision():
    res = run_alembic("sqlite+aiosqlite:///:memory:", "heads")
    assert res.returncode == 0, res.stderr
    heads = [line for line in res.stdout.splitlines() if line.strip()]
    assert heads == [f"{REVISION} (head)"]


def sqlite_columns(db_file, table: str) -> set[str]:
    with sqlite3.connect(db_file) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def sqlite_tables(db_file) -> set[str]:
    with sqlite3.connect(db_file) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_upgrade_and_downgrade_on_sqlite(tmp_path):
    db_file = tmp_path / "db.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    assert run_alembic(db_url, "upgrade", "head").returncode == 0
    assert TABLES <= sqlite_tables(db_file)
    assert "held_proposal_id" in sqlite_columns(db_file, "conversations")
    assert "held_proposal" not in sqlite_columns(db_file, "conversations")
    assert "details" in sqlite_columns(db_file, "messages")

    res = run_alembic(db_url, "downgrade", "-1")
    assert res.returncode == 0, res.stderr
    assert not TABLES & sqlite_tables(db_file)
    assert "held_proposal" in sqlite_columns(db_file, "conversations")
    assert "details" not in sqlite_columns(db_file, "messages")

    assert run_alembic(db_url, "upgrade", "head").returncode == 0
    res = run_alembic(db_url, "check")
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.postgres
def test_upgrade_and_downgrade_on_postgres():
    db_url, drop = with_database("ff_proposal_migration")
    try:
        for step in (("upgrade", "head"), ("check",), ("downgrade", "-1"), ("upgrade", "head")):
            res = run_alembic(db_url, *step)
            assert res.returncode == 0, res.stdout + res.stderr
    finally:
        drop()


def proposal(conversation: Conversation) -> Proposal:
    return Proposal(
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        position=1,
        from_position=0,
        to_position=0,
        raw_text="buy oat milk",
        parts=[{"title": "Oat milk", "summary": "Buy it.", "tags": [], "category": None, "thought_id": None}],
    )


def run(url, work):
    async def main():
        engine = create_engine(url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                alice = await get_or_create_user(session, TEST_ISSUER, "alice")
                return await work(session, alice)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def held_conversation(session, user: User) -> tuple[Conversation, Proposal]:
    conversation = Conversation(user_id=user.id, title="t")
    session.add(conversation)
    await session.flush()
    held = proposal(conversation)
    session.add(held)
    await session.flush()
    conversation.held_proposal_id = held.id
    await session.commit()
    return conversation, held


async def count(session, model, *where) -> int:
    return (await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


def test_deleting_a_conversation_removes_its_proposals(test_database_url):
    async def work(session, alice):
        conversation, _ = await held_conversation(session, alice)
        other, _ = await held_conversation(session, alice)
        await session.execute(delete(Conversation).where(Conversation.id == conversation.id))
        await session.commit()
        return (
            await count(session, Proposal, Proposal.conversation_id == conversation.id),
            await count(session, Proposal, Proposal.conversation_id == other.id),
            await count(
                session,
                Conversation,
                Conversation.held_proposal_id.is_not(None),
                Conversation.held_proposal_id.not_in(select(Proposal.id)),
            ),
        )

    assert run(test_database_url, work) == (0, 1, 0)


def test_deleting_a_user_removes_their_proposals_and_categories(test_database_url):
    async def work(session, alice):
        await held_conversation(session, alice)
        session.add(UserCategory(user_id=alice.id, name="recipe"))
        await session.commit()
        await session.execute(delete(User).where(User.id == alice.id))
        await session.commit()
        return await count(session, Proposal), await count(session, UserCategory)

    assert run(test_database_url, work) == (0, 0)


def test_deleting_a_held_proposal_clears_the_pointer(test_database_url):
    async def work(session, alice):
        conversation, held = await held_conversation(session, alice)
        await session.execute(delete(Proposal).where(Proposal.id == held.id))
        await session.commit()
        await session.refresh(conversation)
        return conversation.held_proposal_id

    assert run(test_database_url, work) is None


def test_a_repeated_category_name_for_one_user_is_refused(test_database_url):
    async def work(session, alice):
        bob = await get_or_create_user(session, TEST_ISSUER, "bob")
        session.add_all(
            [UserCategory(user_id=alice.id, name="recipe"), UserCategory(user_id=bob.id, name="recipe")]
        )
        await session.commit()
        session.add(UserCategory(user_id=alice.id, name="recipe"))
        with pytest.raises(IntegrityError):
            await session.commit()

    run(test_database_url, work)
