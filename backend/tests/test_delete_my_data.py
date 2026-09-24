"""Deleting all of a user's data (thought-storage task 8.1)."""

import uuid

import pytest
from sqlalchemy import func, select

from app.models import SearchIndex, Thought, ThoughtEmbedding, User
from app.thoughts.store import store_thought
from tests.chat_helpers import (
    chat,
    ready_user,
    run_db,
    text_chunks,
    user_id_for,
)
from tests.test_user_data import USER_OWNED, counts
from tests.thought_helpers import run_as

pytestmark = pytest.mark.postgres


def store(url, user_id, fake):
    async def work(session, user, settings, http_client):
        await store_thought(
            session, user, title="Oat milk", summary="Buy oat milk.", raw_text="Detail. " * 200,
            settings=settings, http_client=http_client,
        )

    run_as(url, user_id, fake, work)


def everything(url, user_id) -> dict[str, int]:
    return run_db(url, lambda session: counts(session, uuid.UUID(user_id)))


def give_data(client, headers, fake_llm, url) -> str:
    ready_user(client, headers)
    user_id = user_id_for(client, headers)
    fake_llm.queue(text_chunks("Hello!"))
    assert chat(client, headers, "hi").status_code == 200
    store(url, user_id, fake_llm)
    return user_id


def test_delete_removes_everything_of_the_user_only(client, alice, bob, fake_llm, test_database_url):
    alice_id = give_data(client, alice, fake_llm, test_database_url)
    bob_id = give_data(client, bob, fake_llm, test_database_url)
    before = everything(test_database_url, alice_id)
    bob_before = everything(test_database_url, bob_id)
    assert all(before[model.__tablename__] > 0 for model in (Thought, SearchIndex, ThoughtEmbedding))

    response = client.delete("/api/me", headers=alice)

    assert response.status_code == 204
    assert all(count == 0 for count in everything(test_database_url, alice_id).values())
    assert everything(test_database_url, bob_id) == bob_before
    assert set(before) == {model.__tablename__ for model in USER_OWNED}

    async def user_exists(session):
        query = select(func.count()).select_from(User).where(User.id == uuid.UUID(alice_id))
        return (await session.execute(query)).scalar_one()

    assert run_db(test_database_url, user_exists) == 0


def test_the_next_request_starts_a_new_empty_user(client, alice, fake_llm, test_database_url):
    alice_id = give_data(client, alice, fake_llm, test_database_url)
    assert client.delete("/api/me", headers=alice).status_code == 204

    new_id = user_id_for(client, alice)

    assert new_id != alice_id
    assert client.get("/api/conversations", headers=alice).json()["conversations"] == []
    assert all(count == 0 for count in everything(test_database_url, new_id).values())


def add_demo_user_with_thoughts(url, expires_at) -> uuid.UUID:
    async def work(session):
        user = User(issuer="demo", subject=uuid.uuid4().hex, expires_at=expires_at)
        session.add(user)
        await session.flush()
        thought = Thought(user_id=user.id, title="t", summary="s", tags=[])
        index = SearchIndex(
            user_id=user.id, version=1, embedding_provider="nebius", embedding_model="m",
            dimension=2, status="active",
        )
        session.add_all([thought, index])
        await session.flush()
        session.add(
            ThoughtEmbedding(index_id=index.id, thought_id=thought.id, chunk=0, embedding=[0.1, 0.2])
        )
        await session.commit()
        return user.id

    return run_db(url, work)


def thought_rows(url) -> tuple[int, int, int]:
    async def work(session):
        return tuple(
            [
                (await session.execute(select(func.count()).select_from(model))).scalar_one()
                for model in (Thought, SearchIndex, ThoughtEmbedding)
            ]
        )

    return run_db(url, work)


def test_demo_expiry_removes_thoughts_and_entries(test_database_url):
    from datetime import UTC, datetime, timedelta

    from app.demo import delete_expired_demo_users

    add_demo_user_with_thoughts(test_database_url, datetime.now(UTC) - timedelta(minutes=1))
    assert thought_rows(test_database_url) == (1, 1, 1)
    assert run_db(test_database_url, delete_expired_demo_users) == 1
    assert thought_rows(test_database_url) == (0, 0, 0)


@pytest.fixture
def demo_client(settings_env, test_database_url):
    from fastapi.testclient import TestClient

    from app.main import app

    settings_env.setenv("AUTH_MODE", "demo")
    settings_env.delenv("OIDC_ISSUER")
    settings_env.delenv("OIDC_CLIENT_ID")
    with TestClient(app) as client:
        yield client


def test_end_demo_removes_thoughts_and_entries_and_delete_me_is_404(demo_client, test_database_url):
    value = demo_client.post("/api/demo/sessions").json()["session"]
    headers = {"Authorization": f"Bearer {value}"}
    user_id = uuid.UUID(demo_client.get("/api/me", headers=headers).json()["id"])

    async def add_thought(session):
        index = SearchIndex(
            user_id=user_id, version=1, embedding_provider="nebius", embedding_model="m",
            dimension=2, status="active",
        )
        thought = Thought(user_id=user_id, title="t", summary="s", tags=[])
        session.add_all([index, thought])
        await session.flush()
        session.add(ThoughtEmbedding(index_id=index.id, thought_id=thought.id, chunk=0, embedding=[0.1, 0.2]))
        await session.commit()

    run_db(test_database_url, add_thought)

    response = demo_client.delete("/api/me", headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "not_found")
    assert thought_rows(test_database_url) == (1, 1, 1)

    assert demo_client.delete("/api/demo/session", headers=headers).status_code == 204
    assert thought_rows(test_database_url) == (0, 0, 0)
