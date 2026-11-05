"""Storing and updating a thought's date (thought-dates task 1.2, `thought-store` delta)."""

import uuid

import pytest
from sqlalchemy import Text, cast, func, select

from app.errors import ApiError
from app.models import Thought
from app.thoughts.dates import when_of
from app.thoughts.store import get_thought, store_thought, update_thought
from tests.chat_helpers import MODEL_LIST, FakeLLM, run_db, save_key, user_id_for
from tests.thought_helpers import (
    EMBED_MODEL,
    entries,
    found_by_words,
    models_with_embedding,
    run_as,
)

pytestmark = pytest.mark.postgres

OSLO_DINNER = {"start": "2026-10-02T19:00", "end": None, "time_zone": "Europe/Oslo"}


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def alice_id(client, alice, fake):
    save_key(client, alice)
    fake.embed_requests.clear()
    return user_id_for(client, alice)


def store(url, user_id, fake, **fields):
    async def work(session, user, settings, http_client):
        fields.setdefault("title", "Dinner with Sam")
        fields.setdefault("summary", "Dinner with Sam at the new place.")
        return await store_thought(session, user, settings=settings, http_client=http_client, **fields)

    return run_as(url, user_id, fake, work)


def update(url, user_id, fake, thought_id, **fields):
    async def work(session, user, settings, http_client):
        return await update_thought(
            session, user, thought_id, settings=settings, http_client=http_client, **fields
        )

    return run_as(url, user_id, fake, work)


def read(url, user_id, fake, thought_id) -> Thought:
    async def work(session, user, settings, http_client):
        return await get_thought(session, user, thought_id)

    return run_as(url, user_id, fake, work)


def thought_count(url, user_id) -> int:
    async def work(session):
        query = select(func.count()).select_from(Thought).where(Thought.user_id == uuid.UUID(user_id))
        return (await session.execute(query)).scalar_one()

    return run_db(url, work)


def search_words(url, thought_id) -> str:
    async def work(session):
        query = select(cast(Thought.search_tsv, Text)).where(Thought.id == thought_id)
        return (await session.execute(query)).scalar_one()

    return run_db(url, work)


def test_stored_with_a_date(test_database_url, fake, alice_id):
    outcome = store(test_database_url, alice_id, fake, when=OSLO_DINNER)
    thought = read(test_database_url, alice_id, fake, outcome.thought.id)
    assert when_of(thought) == OSLO_DINNER
    assert thought.ends_on is None and thought.ends_at is None


def test_stored_with_days_and_an_end(test_database_url, fake, alice_id):
    trip = {"start": "2026-11-03", "end": "2026-11-06", "time_zone": "Europe/Oslo"}
    outcome = store(test_database_url, alice_id, fake, title="Trip to Oslo", when=trip)
    assert when_of(read(test_database_url, alice_id, fake, outcome.thought.id)) == trip


@pytest.mark.parametrize("fields", [{}, {"when": None}])
def test_stored_with_no_date(test_database_url, fake, alice_id, fields):
    outcome = store(test_database_url, alice_id, fake, **fields)
    thought = read(test_database_url, alice_id, fake, outcome.thought.id)
    assert when_of(thought) is None
    assert (thought.starts_on, thought.starts_at, thought.ends_on, thought.ends_at, thought.time_zone) == (
        None, None, None, None, None,
    )


@pytest.mark.parametrize(
    "when",
    [
        pytest.param({"start": "2026-11-06", "end": "2026-11-03"}, id="end before start"),
        pytest.param({"start": "2026-10-06T10:00", "end": "2026-10-06"}, id="time on one side only"),
        pytest.param({"start": "next Friday"}, id="not a date"),
        pytest.param({"start": "2026-02-30"}, id="no such day"),
    ],
)
def test_a_bad_date_is_refused_naming_when_and_nothing_is_stored(test_database_url, fake, alice_id, when):
    with pytest.raises(ApiError) as caught:
        store(test_database_url, alice_id, fake, when={**when, "time_zone": "Europe/Oslo"})
    assert caught.value.code == "validation_error"
    assert caught.value.message.startswith("when:")
    assert thought_count(test_database_url, alice_id) == 0
    assert found_by_words(test_database_url, alice_id, "dinner") == []
    assert fake.embed_requests == []


def test_an_unknown_zone_is_stored_as_utc(test_database_url, fake, alice_id):
    outcome = store(
        test_database_url, alice_id, fake, when={"start": "2026-10-02T19:00", "time_zone": "Mars/Base"}
    )
    thought = read(test_database_url, alice_id, fake, outcome.thought.id)
    assert thought.time_zone == "UTC"
    assert when_of(thought) == {"start": "2026-10-02T19:00", "end": None, "time_zone": "UTC"}


@pytest.fixture
def dinner(test_database_url, fake, alice_id) -> uuid.UUID:
    outcome = store(test_database_url, alice_id, fake, raw_text="Sam picked the place. " * 40)
    assert outcome.embedded
    fake.embed_requests.clear()
    return outcome.thought.id


@pytest.mark.parametrize(
    "when",
    [OSLO_DINNER, {"start": "2026-11-03", "end": "2026-11-06", "time_zone": "America/Los_Angeles"}],
)
def test_a_date_only_update_sets_the_date_and_makes_no_embedding_call(
    test_database_url, fake, alice_id, dinner, when
):
    before_entries = entries(test_database_url, dinner)
    assert before_entries and len(before_entries[next(iter(before_entries))]) > 1
    before_words = search_words(test_database_url, dinner)

    outcome = update(test_database_url, alice_id, fake, dinner, when=when)

    assert when_of(outcome.thought) == when
    assert when_of(read(test_database_url, alice_id, fake, dinner)) == when
    assert fake.embed_requests == []
    assert entries(test_database_url, dinner) == before_entries
    assert search_words(test_database_url, dinner) == before_words


def test_a_null_date_clears_it_and_a_missing_one_keeps_it(test_database_url, fake, alice_id, dinner):
    update(test_database_url, alice_id, fake, dinner, when=OSLO_DINNER)
    update(test_database_url, alice_id, fake, dinner, category="event")
    assert when_of(read(test_database_url, alice_id, fake, dinner)) == OSLO_DINNER

    update(test_database_url, alice_id, fake, dinner, when=None)
    thought = read(test_database_url, alice_id, fake, dinner)
    assert when_of(thought) is None
    assert thought.time_zone is None
    assert fake.embed_requests == []


def test_a_bad_date_update_is_refused_and_the_thought_is_unchanged(test_database_url, fake, alice_id, dinner):
    update(test_database_url, alice_id, fake, dinner, when=OSLO_DINNER)
    with pytest.raises(ApiError) as caught:
        update(
            test_database_url, alice_id, fake, dinner,
            title="Lunch with Sam", when={"start": "2026-11-06", "end": "2026-11-03"},
        )
    assert caught.value.message.startswith("when:")
    thought = read(test_database_url, alice_id, fake, dinner)
    assert (thought.title, when_of(thought)) == ("Dinner with Sam", OSLO_DINNER)
    assert fake.embed_requests == []
