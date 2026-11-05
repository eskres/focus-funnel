"""A thought's status in the store: set_status() (thought-status task 1.2)."""

import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import get_or_create_user
from app.db import create_engine
from app.errors import ApiError
from app.models import (
    Conversation,
    Proposal,
    SearchIndex,
    Thought,
    ThoughtEmbedding,
    User,
)
from app.thoughts.search import search_thoughts
from app.thoughts.store import set_status, store_thought
from tests.chat_helpers import MODEL_LIST, FakeLLM, run_db
from tests.conftest import TEST_ISSUER
from tests.thought_helpers import (
    EMBED_MODEL,
    counted_queries,
    models_with_embedding,
    run_as,
)

A_DAY_BACK = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0)


def utc(value: datetime | None) -> datetime | None:
    """SQLite reads times back without a zone; they are UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def make_user(url: str, subject: str) -> str:
    async def work(session):
        user = await get_or_create_user(session, TEST_ISSUER, subject)
        await session.commit()
        return str(user.id)

    return run_db(url, work)


def seed(url: str, user_id: str, title: str = "Call the plumber", **fields) -> str:
    async def work(session):
        thought = Thought(
            user_id=uuid.UUID(user_id),
            title=title,
            summary=f"{title}: the summary.",
            tags=["home"],
            category="task",
            **fields,
        )
        session.add(thought)
        await session.commit()
        return str(thought.id)

    return run_db(url, work)


def read(url: str, thought_id: str) -> Thought | None:
    async def work(session):
        return await session.get(Thought, uuid.UUID(thought_id))

    return run_db(url, work)


def set_columns(url: str, thought_id: str, **values) -> None:
    """A direct UPDATE, as another request or a test setup would make it."""

    async def work(session):
        await session.execute(
            update(Thought).where(Thought.id == uuid.UUID(thought_id)).values(**values)
        )
        await session.commit()

    run_db(url, work)


def call(url: str, user_id: str, thought_id, status):
    """set_status() and a commit; the thought it returned, or the ApiError."""

    async def work(session):
        user = await session.get(User, uuid.UUID(user_id))
        try:
            thought = await set_status(session, user, uuid.UUID(str(thought_id)), status)
        except ApiError as error:
            return error
        await session.commit()
        return thought

    return run_db(url, work)


def body(error: ApiError) -> tuple[int, str, str]:
    return error.status_code, error.code, error.message


@pytest.fixture
def db(test_database_url):
    alice = make_user(test_database_url, "alice")
    bob = make_user(test_database_url, "bob")
    return test_database_url, alice, bob


def test_a_new_thought_is_open_with_no_change_time(db):
    url, alice, _ = db
    thought = read(url, seed(url, alice))
    assert thought.status == "open"
    assert thought.status_changed_at is None


def test_done_sets_the_status_and_a_change_time(db):
    url, alice, _ = db
    thought_id = seed(url, alice)
    returned = call(url, alice, thought_id, "done")
    assert returned.status == "done"
    assert returned.status_changed_at is not None
    stored = read(url, thought_id)
    assert stored.status == "done"
    assert utc(stored.status_changed_at) == utc(returned.status_changed_at)


def test_open_again_sets_a_later_change_time(db):
    url, alice, _ = db
    thought_id = seed(url, alice)
    call(url, alice, thought_id, "done")
    set_columns(url, thought_id, status_changed_at=A_DAY_BACK)

    returned = call(url, alice, thought_id, "open")
    assert returned.status == "open"
    stored = read(url, thought_id)
    assert stored.status == "open"
    assert utc(stored.status_changed_at) > A_DAY_BACK


@pytest.mark.parametrize("status", ["archived", "Done", "", None, 1])
def test_not_a_status_is_refused_and_the_thought_is_unchanged(db, status):
    url, alice, _ = db
    thought_id = seed(url, alice)
    error = call(url, alice, thought_id, status)
    assert isinstance(error, ApiError)
    assert body(error) == (422, "validation_error", "status: must be open or done")
    stored = read(url, thought_id)
    assert (stored.status, stored.status_changed_at) == ("open", None)


def test_another_users_thought_and_a_missing_one_are_not_found_alike(db):
    url, alice, bob = db
    bobs = seed(url, bob, "Bob's task")
    foreign = call(url, alice, bobs, "done")
    missing = call(url, alice, uuid.uuid4(), "done")
    assert isinstance(foreign, ApiError) and isinstance(missing, ApiError)
    assert body(foreign) == body(missing) == (404, "not_found", "No such thought.")
    stored = read(url, bobs)
    assert (stored.status, stored.status_changed_at) == ("open", None)


def test_the_same_status_again_keeps_the_change_time(db):
    url, alice, _ = db
    thought_id = seed(url, alice)
    call(url, alice, thought_id, "done")
    set_columns(url, thought_id, status_changed_at=A_DAY_BACK)

    returned = call(url, alice, thought_id, "done")
    assert returned.status == "done"
    stored = read(url, thought_id)
    assert stored.status == "done"
    assert utc(stored.status_changed_at) == A_DAY_BACK


# --- A status change leaves the rest of the thought alone --------------------


def seed_full(url: str, user_id: str) -> str:
    """A dated thought with raw text, an origin, and two search entries,
    last updated a day back."""

    async def work(session):
        conversation = Conversation(user_id=uuid.UUID(user_id), title="Home")
        session.add(conversation)
        await session.flush()
        proposal = Proposal(
            conversation_id=conversation.id, user_id=uuid.UUID(user_id), position=1,
            from_position=0, to_position=0, parts=[], raw_text="Call him.",
        )
        session.add(proposal)
        await session.flush()
        thought = Thought(
            user_id=uuid.UUID(user_id),
            title="Call the plumber",
            summary="Ask about the leak under the sink.",
            raw_text="The sink leaks; call the plumber.",
            tags=["home", "repairs"],
            category="task",
            proposal_id=proposal.id,
            starts_on=date(2026, 11, 9),
            starts_at=time(9, 30),
            time_zone="Europe/Lisbon",
        )
        index = SearchIndex(
            user_id=uuid.UUID(user_id),
            version=1,
            embedding_provider="nebius",
            embedding_model=EMBED_MODEL,
            dimension=2,
            status="active",
        )
        session.add_all([thought, index])
        await session.flush()
        session.add_all(
            [
                ThoughtEmbedding(index_id=index.id, thought_id=thought.id, chunk=0, embedding=[0.5, 0.25]),
                ThoughtEmbedding(
                    index_id=index.id, thought_id=thought.id, chunk=1, start_char=0, end_char=12,
                    embedding=[0.75, 0.125],
                ),
            ]
        )
        await session.commit()
        return str(thought.id)

    thought_id = run_db(url, work)
    set_columns(url, thought_id, updated_at=A_DAY_BACK)
    return thought_id


CONTENT = (
    "title", "summary", "raw_text", "tags", "category", "proposal_id",
    "starts_on", "starts_at", "ends_on", "ends_at", "time_zone", "created_at",
)


def content(thought: Thought) -> dict:
    return {
        **{name: getattr(thought, name) for name in CONTENT},
        "created_at": utc(thought.created_at),
        "updated_at": utc(thought.updated_at),
    }


def embedding_rows(url: str, thought_id: str) -> list[tuple]:
    async def work(session):
        rows = await session.execute(
            select(
                ThoughtEmbedding.id, ThoughtEmbedding.index_id, ThoughtEmbedding.chunk,
                ThoughtEmbedding.start_char, ThoughtEmbedding.end_char, ThoughtEmbedding.embedding,
            )
            .where(ThoughtEmbedding.thought_id == uuid.UUID(thought_id))
            .order_by(ThoughtEmbedding.chunk)
        )
        return [tuple(str(value) for value in row) for row in rows]

    return run_db(url, work)


def check_done_keeps_the_rest(url: str, alice: str):
    thought_id = seed_full(url, alice)
    before = content(read(url, thought_id))
    assert before["updated_at"] == A_DAY_BACK
    entries_before = embedding_rows(url, thought_id)
    assert len(entries_before) == 2
    fake = FakeLLM(models=models_with_embedding(MODEL_LIST))

    async def work(session, user, settings, http_client):
        await set_status(session, user, uuid.UUID(thought_id), "done")
        await session.flush()
        await session.commit()

    with counted_queries() as statements:
        run_as(url, alice, fake, work)

    after = read(url, thought_id)  # a new session
    assert after.status == "done"
    assert content(after) == before
    assert embedding_rows(url, thought_id) == entries_before
    assert fake.embed_requests == [] and fake.chat_requests == []

    [statement] = [s for s in statements if s.lstrip().upper().startswith("UPDATE THOUGHTS")]
    set_clause, where = statement.split(" WHERE ")
    assignments = dict(
        item.replace(" ", "").split("=", 1) for item in set_clause.split(" SET ", 1)[1].split(",")
    )
    # updated_at is set to the column itself, never to now().
    assert assignments["updated_at"] == "thoughts.updated_at", statement
    assert assignments["status_changed_at"].lower() in {"now()", "current_timestamp"}, statement
    assert "thoughts.status !=" in where, statement


def test_done_keeps_the_rest_on_sqlite(db):
    url, alice, _ = db
    assert url.startswith("sqlite")
    check_done_keeps_the_rest(url, alice)


@pytest.mark.postgres
def test_done_keeps_the_rest_on_postgres(db):
    url, alice, _ = db
    assert url.startswith("postgresql")
    check_done_keeps_the_rest(url, alice)


@pytest.mark.postgres
def test_a_word_search_still_finds_a_done_thought(db, settings_env):
    url, alice, _ = db
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    fake = FakeLLM(models=models_with_embedding(MODEL_LIST))

    async def store(session, user, settings, http_client):
        outcome = await store_thought(
            session, user, settings=settings, http_client=http_client,
            title="Call the plumber", summary="Ask about the leak.", tags=["home"], category="task",
        )
        return str(outcome.thought.id)

    thought_id = run_as(url, alice, fake, store)
    call(url, alice, thought_id, "done")

    async def search(session, user, settings, http_client):
        result = await search_thoughts(session, user, "plumber", settings=settings, http_client=http_client)
        return [(str(hit.thought.id), hit.thought.status) for hit in result.hits]

    assert run_as(url, alice, fake, search) == [(thought_id, "done")]


# --- Races between two sessions ----------------------------------------------


def two_sessions(url: str, work):
    import asyncio

    async def main():
        engine = create_engine(url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as a, sessions() as b:
                return await work(a, b)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def check_a_racing_done_keeps_the_first_change_time(url: str, alice: str):
    thought_id = uuid.UUID(seed(url, alice))

    async def work(a, b):
        user_a = await a.get(User, uuid.UUID(alice))
        loaded = await a.get(Thought, thought_id)
        assert loaded.status == "open"

        user_b = await b.get(User, uuid.UUID(alice))
        await set_status(b, user_b, thought_id, "done")
        await b.commit()
        await b.execute(
            update(Thought).where(Thought.id == thought_id).values(status_changed_at=A_DAY_BACK)
        )
        await b.commit()

        returned = await set_status(a, user_a, thought_id, "done")
        assert returned is loaded
        assert returned.status == "done"
        await a.commit()

    two_sessions(url, work)
    stored = read(url, str(thought_id))
    assert stored.status == "done"
    assert utc(stored.status_changed_at) == A_DAY_BACK


def check_a_thought_deleted_meanwhile_is_not_found(url: str, alice: str):
    thought_id = uuid.UUID(seed(url, alice))

    async def work(a, b):
        user_a = await a.get(User, uuid.UUID(alice))
        await a.get(Thought, thought_id)
        await b.delete(await b.get(Thought, thought_id))
        await b.commit()
        with pytest.raises(ApiError) as raised:
            await set_status(a, user_a, thought_id, "done")
        return raised.value

    error = two_sessions(url, work)
    assert body(error) == (404, "not_found", "No such thought.")


def test_a_racing_done_keeps_the_first_change_time(db):
    url, alice, _ = db
    check_a_racing_done_keeps_the_first_change_time(url, alice)


def test_a_thought_deleted_meanwhile_is_not_found(db):
    url, alice, _ = db
    check_a_thought_deleted_meanwhile_is_not_found(url, alice)


@pytest.mark.postgres
def test_the_races_on_postgres(db):
    url, alice, _ = db
    check_a_racing_done_keeps_the_first_change_time(url, alice)
    check_a_thought_deleted_meanwhile_is_not_found(url, alice)
