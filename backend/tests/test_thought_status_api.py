"""A thought's status through GET and PATCH /api/thoughts/{id} (thought-status task 1.3)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.models import Thought
from tests.chat_helpers import MODEL_LIST, FakeLLM, error_code, run_db, user_id_for
from tests.test_thought_refs import seed_thought
from tests.thought_helpers import models_with_embedding

A_DAY_BACK = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0)


def when(value: str) -> datetime:
    """An answered time; SQLite's come without a zone and are UTC."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@pytest.fixture
def fake(client) -> FakeLLM:
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


def seed(url, user_id, title="Call the plumber") -> str:
    """A task thought last updated a day back."""
    thought_id = seed_thought(url, user_id, title, category="task")

    async def work(session):
        await session.execute(
            update(Thought).where(Thought.id == uuid.UUID(thought_id)).values(updated_at=A_DAY_BACK)
        )
        await session.commit()

    run_db(url, work)
    return thought_id


@pytest.fixture
def alices(client, alice, fake, test_database_url) -> str:
    return seed(test_database_url, user_id_for(client, alice))


@pytest.fixture
def bobs(client, bob, fake, test_database_url) -> str:
    return seed(test_database_url, user_id_for(client, bob), "Bob's task")


def get(client, headers, thought_id) -> dict:
    response = client.get(f"/api/thoughts/{thought_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def patch(client, headers, thought_id, body):
    return client.patch(f"/api/thoughts/{thought_id}", headers=headers, json=body)


def test_get_answers_the_status_and_its_change_time(client, alice, alices):
    answer = get(client, alice, alices)
    assert answer["status"] == "open"
    assert answer["status_changed_at"] is None


def test_done_answers_the_status_and_keeps_updated_at(client, alice, alices, fake):
    before = get(client, alice, alices)

    response = patch(client, alice, alices, {"status": "done"})

    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["status"] == "done"
    assert answer["status_changed_at"] is not None
    assert when(answer["status_changed_at"]) > A_DAY_BACK
    assert answer["updated_at"] == before["updated_at"]
    assert when(answer["updated_at"]) == A_DAY_BACK
    unchanged = {key: value for key, value in answer.items() if not key.startswith("status")}
    assert unchanged == {key: value for key, value in before.items() if not key.startswith("status")}
    assert get(client, alice, alices) == answer
    assert fake.embed_requests == [] and fake.chat_requests == []


@pytest.mark.parametrize("status", ["archived", None, "", ["done"]])
def test_not_a_status_is_refused_naming_status(client, alice, alices, status):
    before = get(client, alice, alices)

    response = patch(client, alice, alices, {"status": status})

    assert response.status_code == 422, response.text
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"] == "status: must be open or done"
    assert get(client, alice, alices) == before


def test_a_refused_title_after_the_status_leaves_it_open(client, alice, alices):
    before = get(client, alice, alices)

    response = patch(client, alice, alices, {"status": "done", "title": ""})

    assert response.status_code == 422, response.text
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith("title: ")
    after = get(client, alice, alices)
    assert after == before
    assert after["status"] == "open"


@pytest.mark.parametrize("body", [{"status": "done"}, {"status": "done", "category": "idea"}])
def test_another_users_thought_is_not_found_like_an_unknown_id(client, alice, bob, alices, bobs, body):
    foreign = patch(client, alice, bobs, body)
    unknown = patch(client, alice, str(uuid.uuid4()), body)

    assert foreign.status_code == unknown.status_code == 404, foreign.text
    assert error_code(foreign) == "not_found"
    assert foreign.json() == unknown.json()
    theirs = get(client, bob, bobs)
    assert theirs["status"] == "open"
    assert theirs["status_changed_at"] is None


@pytest.mark.postgres
def test_done_with_a_title_changes_both_and_moves_updated_at(client, alice, alices):
    before = get(client, alice, alices)

    response = patch(client, alice, alices, {"status": "done", "title": "Plumber called"})

    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["status"] == "done"
    assert answer["status_changed_at"] is not None
    assert answer["title"] == "Plumber called"
    assert when(answer["updated_at"]) > when(before["updated_at"])
    assert get(client, alice, alices) == answer
