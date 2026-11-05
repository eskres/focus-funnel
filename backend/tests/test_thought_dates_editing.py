"""Editing a thought's date through PATCH /api/thoughts/{id} (thought-dates task 4.1)."""

import uuid
from datetime import date, time

import pytest

from app.models import Thought
from tests.chat_helpers import (
    MODEL_LIST,
    FakeLLM,
    error_code,
    ready_user,
    run_db,
    user_id_for,
)
from tests.test_thought_editing import LONG_RAW, patch, saved_thought, thought
from tests.thought_helpers import (
    EMBED_MODEL,
    entries,
    found_by_words,
    models_with_embedding,
)

pytestmark = pytest.mark.postgres

DINNER = {"start": "2026-10-02T19:00", "end": None, "time_zone": "Europe/Oslo"}
TRIP = {"start": "2026-11-03", "end": "2026-11-06", "time_zone": "Europe/Oslo"}


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def alices(client, alice, fake, test_database_url) -> dict:
    """A saved thought with no date and several search entries."""
    ready_user(client, alice)
    saved = saved_thought(client, alice, test_database_url, raw_text=LONG_RAW)
    fake.embed_requests.clear()
    return saved


def stored_columns(url, thought_id) -> tuple:
    async def work(session):
        row = await session.get(Thought, uuid.UUID(thought_id))
        return (row.starts_on, row.starts_at, row.ends_on, row.ends_at, row.time_zone)

    return run_db(url, work)


def search_state(url, user_id, thought_id) -> tuple:
    """What search finds the thought by: its words, and its entries by meaning."""
    return found_by_words(url, user_id, "oat milk"), entries(url, thought_id)


def test_get_answers_no_date_for_a_thought_without_one(client, alice, alices):
    assert thought(client, alice, alices["thought_id"])["when"] is None


def test_patch_sets_changes_and_clears_the_date(client, alice, alices, fake, test_database_url):
    thought_id = alices["thought_id"]
    user_id = user_id_for(client, alice)
    search_before = search_state(test_database_url, user_id, thought_id)
    before = thought(client, alice, thought_id)

    set_ = patch(client, alice, thought_id, {"when": DINNER})
    assert set_.status_code == 200, set_.text
    assert set_.json()["when"] == DINNER
    assert thought(client, alice, thought_id)["when"] == DINNER
    assert stored_columns(test_database_url, thought_id) == (
        date(2026, 10, 2),
        time(19, 0),
        None,
        None,
        "Europe/Oslo",
    )
    # Only the date changed.
    kept = {"title", "summary", "tags", "category", "raw_text", "created_at", "origin"}
    assert {key: set_.json()[key] for key in kept} == {key: before[key] for key in kept}

    changed = patch(client, alice, thought_id, {"when": TRIP})
    assert changed.status_code == 200, changed.text
    assert changed.json()["when"] == TRIP
    assert stored_columns(test_database_url, thought_id) == (
        date(2026, 11, 3),
        None,
        date(2026, 11, 6),
        None,
        "Europe/Oslo",
    )

    # A field the body leaves out keeps the date.
    titled = patch(client, alice, thought_id, {"category": "idea"})
    assert titled.json()["when"] == TRIP

    cleared = patch(client, alice, thought_id, {"when": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["when"] is None
    assert thought(client, alice, thought_id)["when"] is None
    assert stored_columns(test_database_url, thought_id) == (None,) * 5

    # Date-only changes made no embedding call and left the search entries alone.
    assert fake.embed_requests == []
    assert search_state(test_database_url, user_id, thought_id) == search_before


def test_an_unknown_zone_is_stored_as_utc(client, alice, alices):
    response = patch(client, alice, alices["thought_id"], {"when": {**DINNER, "time_zone": "Mars/Base"}})

    assert response.status_code == 200, response.text
    assert response.json()["when"] == {**DINNER, "time_zone": "UTC"}


@pytest.mark.parametrize(
    "when",
    [
        {"start": "2026-10-02T19:00", "end": "2026-10-02T18:00", "time_zone": "Europe/Oslo"},
        {"start": "2026-11-06", "end": "2026-11-03", "time_zone": "Europe/Oslo"},
        {"start": "2026-10-02T19:00", "end": "2026-10-03", "time_zone": "Europe/Oslo"},
        {"start": "next Friday", "end": None, "time_zone": "Europe/Oslo"},
        {"start": "2026-02-30", "end": None, "time_zone": "Europe/Oslo"},
        {"start": None, "end": "2026-10-02"},
        "2026-10-02",
    ],
)
def test_a_refused_date_names_when_and_the_thought_is_unchanged(
    client, alice, alices, fake, test_database_url, when
):
    thought_id = alices["thought_id"]
    assert patch(client, alice, thought_id, {"when": DINNER}).status_code == 200
    user_id = user_id_for(client, alice)
    search_before = search_state(test_database_url, user_id, thought_id)
    before = thought(client, alice, thought_id)

    response = patch(client, alice, thought_id, {"title": "Dinner with Sam", "when": when})

    assert response.status_code == 422, response.text
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith("when: ")
    assert thought(client, alice, thought_id) == before
    assert fake.embed_requests == []
    assert search_state(test_database_url, user_id, thought_id) == search_before


def test_end_before_start_is_refused_naming_when(client, alice, alices):
    response = patch(
        client,
        alice,
        alices["thought_id"],
        {"when": {"start": "2026-11-06", "end": "2026-11-03", "time_zone": "Europe/Oslo"}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "when: the end must not be before the start"
    assert thought(client, alice, alices["thought_id"])["when"] is None


def test_a_date_and_a_title_change_together_embed_once(client, alice, alices, fake):
    response = patch(client, alice, alices["thought_id"], {"title": "Dinner with Sam", "when": DINNER})

    assert response.status_code == 200, response.text
    assert (response.json()["title"], response.json()["when"]) == ("Dinner with Sam", DINNER)
    assert len(fake.embed_requests) == 1
