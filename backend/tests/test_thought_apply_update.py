"""apply_update(), the part of update_thought() that does not commit
(thought-appending task 1.2)."""

import pytest
from sqlalchemy import select
from sqlalchemy.pool import NullPool

from app.db import create_engine
from app.models import Thought, ThoughtEmbedding
from app.thoughts.store import apply_update, get_thought
from tests import test_thought_store
from tests.chat_helpers import run_db
from tests.thought_helpers import (
    EMBED_MODEL,
    entries,
    found_by_words,
    head_texts,
    run_as,
)

pytestmark = pytest.mark.postgres

# The store tests' fixtures and helpers.
fake = test_thought_store.fake
alice_id = test_thought_store.alice_id
store = test_thought_store.store
LONG_RAW = test_thought_store.LONG_RAW


def snapshot(url, thought_id):
    """The thought's row and every entry it has, with vectors."""

    async def work(session):
        thought = (
            await session.execute(
                select(
                    Thought.title, Thought.summary, Thought.tags, Thought.raw_text,
                    Thought.category, Thought.updated_at, Thought.search_tsv,
                ).where(Thought.id == thought_id)
            )
        ).one()
        rows = await session.execute(
            select(
                ThoughtEmbedding.id, ThoughtEmbedding.index_id, ThoughtEmbedding.chunk,
                ThoughtEmbedding.start_char, ThoughtEmbedding.end_char, ThoughtEmbedding.embedding,
            )
            .where(ThoughtEmbedding.thought_id == thought_id)
            .order_by(ThoughtEmbedding.chunk)
        )
        return tuple(thought), [(*row[:5], [float(x) for x in row[5]]) for row in rows]

    return run_db(url, work)


def apply_then_roll_back(url, user_id, fake, thought_id, **fields):
    """Apply the change, look at it inside the transaction, and roll back."""

    async def work(session, user, settings, http_client):
        thought = await get_thought(session, user, thought_id)
        outcome = await apply_update(
            session, user, thought, settings=settings, http_client=http_client, **fields
        )
        inside = (
            await session.execute(
                select(Thought.summary, Thought.tags, Thought.category).where(Thought.id == thought_id)
            )
        ).one()
        chunks = list(
            (
                await session.execute(
                    select(ThoughtEmbedding.chunk).where(ThoughtEmbedding.thought_id == thought_id)
                )
            ).scalars()
        )
        await session.rollback()
        return outcome, tuple(inside), sorted(chunks)

    return run_as(url, user_id, fake, work)


@pytest.mark.parametrize(
    "fields",
    [
        {"summary": "Book the dentist.", "raw_text": None},
        {"tags": ["groceries"]},
        {"category": "errand"},
        {"summary": "Book the dentist.", "tags": ["health"], "category": "to-do", "raw_text": "Short."},
    ],
)
def test_apply_update_then_rollback_leaves_the_thought_and_its_entries(
    test_database_url, fake, alice_id, fields
):
    thought_id = store(test_database_url, alice_id, fake, raw_text=LONG_RAW, tags=["shop"]).thought.id
    before = snapshot(test_database_url, thought_id)
    assert before[1], "the stored thought has entries"
    fake.embed_requests.clear()

    outcome, inside, chunks = apply_then_roll_back(test_database_url, alice_id, fake, thought_id, **fields)

    # Inside the transaction the change was there: fields and new entries.
    assert outcome.embedded
    for name, value in fields.items():
        if name in ("summary", "tags", "category"):
            assert inside[("summary", "tags", "category").index(name)] == value
    if "summary" in fields or "tags" in fields:
        assert len(fake.embed_requests) == 1
    if "raw_text" in fields:
        # The long raw text's chunks went; only the new pieces are there.
        assert chunks == ([0] if fields["raw_text"] is None else [0, 1])
    # After the rollback nothing of it is left.
    assert snapshot(test_database_url, thought_id) == before
    assert found_by_words(test_database_url, alice_id, "dentist") == []
    assert found_by_words(test_database_url, alice_id, "oat") == ["Oat milk"]


def test_apply_update_does_not_commit_and_the_caller_can(test_database_url, fake, alice_id):
    thought_id = store(test_database_url, alice_id, fake).thought.id
    fake.embed_requests.clear()

    async def work(session, user, settings, http_client):
        thought = await get_thought(session, user, thought_id)
        await apply_update(
            session, user, thought, summary="Book the dentist.", settings=settings, http_client=http_client
        )
        # A second connection does not see it yet.
        engine = create_engine(test_database_url, poolclass=NullPool)
        try:
            async with engine.connect() as other:
                seen = await other.scalar(select(Thought.summary).where(Thought.id == thought_id))
        finally:
            await engine.dispose()
        await session.commit()
        return seen

    assert run_as(test_database_url, alice_id, fake, work) == "Buy oat milk on the way home."
    assert head_texts(fake) == ["Oat milk\nBook the dentist."]
    assert entries(test_database_url, thought_id) == {f"active:{EMBED_MODEL}": [0]}
    assert found_by_words(test_database_url, alice_id, "dentist") == ["Oat milk"]
