"""Confirm stores the card's date (thought-dates task 2.4)."""

import uuid
from datetime import date, time

import pytest
from sqlalchemy import select

from app.models import Proposal, Thought
from app.thoughts.dates import when_of
from tests.chat_helpers import (
    MODEL_LIST,
    FakeLLM,
    error_code,
    part,
    run_db,
    save_key,
    seed_conversation,
    seed_proposal,
)
from tests.thought_helpers import EMBED_MODEL, models_with_embedding

pytestmark = pytest.mark.postgres

OSLO_DINNER = {"start": "2026-10-02T19:00", "end": None, "time_zone": "Europe/Oslo"}
CHOICES = [
    {"start": "2026-10-02T19:00", "end": None, "time_zone": "Europe/Oslo"},
    {"start": "2026-10-09T19:00", "end": None, "time_zone": "Europe/Oslo"},
]


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def conversation_id(client, alice, fake, test_database_url) -> str:
    save_key(client, alice)
    return seed_conversation(test_database_url, client, alice)


def dinner(**fields) -> dict:
    return {**part(title="Dinner with Sam", tags=["sam"]), **fields}


def confirm(client, headers, conversation_id, proposal_id, **fields):
    body = {
        "parts": [0],
        "title": "Dinner with Sam",
        "summary": "Dinner at Sam's.",
        "tags": ["sam"],
        "category": "task",
        **fields,
    }
    return client.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal_id}/confirm",
        headers=headers,
        json=body,
    )


def thoughts(url) -> list[Thought]:
    async def work(session):
        return list((await session.execute(select(Thought).order_by(Thought.created_at))).scalars())

    return run_db(url, work)


def parts_of(url, proposal_id) -> list[dict]:
    return run_db(url, lambda session: session.get(Proposal, uuid.UUID(proposal_id))).parts


def test_confirm_stores_the_cards_date_with_the_browsers_zone(
    client, alice, conversation_id, test_database_url
):
    # The part was proposed in Oslo; the user confirms from Tokyo, at 19:30.
    proposal_id = seed_proposal(test_database_url, conversation_id, [dinner(when=OSLO_DINNER)])
    when = {"start": "2026-10-02T19:30", "end": None, "time_zone": "Asia/Tokyo"}

    response = confirm(client, alice, conversation_id, proposal_id, when=when)

    assert response.status_code == 200, response.text
    [thought] = thoughts(test_database_url)
    assert (thought.starts_on, thought.starts_at, thought.ends_on, thought.ends_at, thought.time_zone) == (
        date(2026, 10, 2), time(19, 30), None, None, "Asia/Tokyo",
    )
    assert when_of(thought) == when


def test_confirm_stores_days_with_an_end(client, alice, conversation_id, test_database_url):
    proposal_id = seed_proposal(test_database_url, conversation_id, [dinner()])
    when = {"start": "2026-11-03", "end": "2026-11-06", "time_zone": "Europe/Oslo"}

    response = confirm(client, alice, conversation_id, proposal_id, when=when)

    assert response.status_code == 200, response.text
    assert when_of(thoughts(test_database_url)[0]) == when


def test_a_date_cleared_on_the_card_stores_no_date(client, alice, conversation_id, test_database_url):
    proposal_id = seed_proposal(test_database_url, conversation_id, [dinner(when=OSLO_DINNER)])

    response = confirm(client, alice, conversation_id, proposal_id, when=None)

    assert response.status_code == 200, response.text
    [thought] = thoughts(test_database_url)
    assert when_of(thought) is None
    assert (thought.starts_on, thought.starts_at, thought.ends_on, thought.ends_at, thought.time_zone) == (
        None, None, None, None, None,
    )


def test_an_end_before_the_start_is_refused_naming_when_and_nothing_is_stored(
    client, alice, conversation_id, test_database_url
):
    proposal_id = seed_proposal(test_database_url, conversation_id, [dinner(when=OSLO_DINNER)])

    response = confirm(
        client, alice, conversation_id, proposal_id,
        when={"start": "2026-11-06", "end": "2026-11-03", "time_zone": "Europe/Oslo"},
    )

    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith("when: ")
    assert thoughts(test_database_url) == []
    assert parts_of(test_database_url, proposal_id)[0]["thought_id"] is None


def test_a_part_with_choices_and_no_pick_is_refused_naming_when_and_nothing_is_stored(
    client, alice, conversation_id, test_database_url
):
    proposal_id = seed_proposal(
        test_database_url, conversation_id, [dinner(when=None, when_choices=CHOICES)]
    )

    response = confirm(client, alice, conversation_id, proposal_id)

    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith("when: pick a date")
    assert thoughts(test_database_url) == []
    assert parts_of(test_database_url, proposal_id)[0]["thought_id"] is None


def test_a_part_with_choices_and_when_null_stores_no_date(
    client, alice, conversation_id, test_database_url
):
    proposal_id = seed_proposal(
        test_database_url, conversation_id, [dinner(when=None, when_choices=CHOICES)]
    )

    response = confirm(client, alice, conversation_id, proposal_id, when=None)

    assert response.status_code == 200, response.text
    assert when_of(thoughts(test_database_url)[0]) is None


def test_a_part_with_choices_stores_the_picked_choice(client, alice, conversation_id, test_database_url):
    proposal_id = seed_proposal(
        test_database_url, conversation_id, [dinner(when=None, when_choices=CHOICES)]
    )

    response = confirm(client, alice, conversation_id, proposal_id, when=CHOICES[1])

    assert response.status_code == 200, response.text
    assert when_of(thoughts(test_database_url)[0]) == CHOICES[1]


@pytest.mark.parametrize("stored", [{}, {"when": OSLO_DINNER}, {"when": None, "when_choices": None}])
def test_a_part_without_choices_and_no_when_key_stores_no_date(
    client, alice, conversation_id, test_database_url, stored
):
    proposal_id = seed_proposal(test_database_url, conversation_id, [dinner(**stored)])

    response = confirm(client, alice, conversation_id, proposal_id)

    assert response.status_code == 200, response.text
    assert when_of(thoughts(test_database_url)[0]) is None


def test_a_merge_follows_the_first_parts_choices(client, alice, conversation_id, test_database_url):
    proposal_id = seed_proposal(
        test_database_url,
        conversation_id,
        [dinner(when=None, when_choices=CHOICES), part(title="Wine", category="task")],
    )

    refused = confirm(client, alice, conversation_id, proposal_id, parts=[0, 1])
    picked = confirm(client, alice, conversation_id, proposal_id, parts=[0, 1], when=CHOICES[0])

    assert refused.status_code == 422
    assert refused.json()["error"]["message"].startswith("when: ")
    assert picked.status_code == 200, picked.text
    [thought] = thoughts(test_database_url)
    assert when_of(thought) == CHOICES[0]
    assert [p["thought_id"] for p in parts_of(test_database_url, proposal_id)] == [str(thought.id)] * 2


def test_a_merge_whose_first_part_has_no_choices_needs_no_pick(
    client, alice, conversation_id, test_database_url
):
    proposal_id = seed_proposal(
        test_database_url,
        conversation_id,
        [part(title="Wine", category="task"), dinner(when=None, when_choices=CHOICES)],
    )

    response = confirm(client, alice, conversation_id, proposal_id, parts=[0, 1])

    assert response.status_code == 200, response.text
    assert when_of(thoughts(test_database_url)[0]) is None
