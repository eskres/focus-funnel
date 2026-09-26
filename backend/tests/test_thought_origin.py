"""A thought's origin: deletions (explore task 1.2), saving the link (2.1),
and the detail answer's origin (2.2)."""

import json
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Engine

from app.models import Proposal, Thought
from app.thoughts.search import search_thoughts
from app.thoughts.store import store_thought
from tests.chat_helpers import (
    MODEL_LIST,
    FakeLLM,
    chat,
    part,
    ready_user,
    run_db,
    seed_conversation,
    seed_proposal,
    text_chunks,
    tool_call_chunks,
    user_id_for,
)
from tests.thought_helpers import EMBED_MODEL, models_with_embedding, run_as

pytestmark = pytest.mark.postgres

RAW = "buy oat milk, and book the dentist"


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def conversation_id(client, alice, fake, test_database_url) -> str:
    ready_user(client, alice)
    return seed_conversation(test_database_url, client, alice, title="Groceries")


def two_parts(url, conversation_id) -> str:
    return seed_proposal(
        url,
        conversation_id,
        [part(title="Oat milk", tags=["groceries"]), part(title="Dentist", tags=["health"])],
        raw_text=RAW,
    )


def confirm(client, headers, conversation_id, proposal_id, parts=(0,), title="Oat milk"):
    response = client.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal_id}/confirm",
        headers=headers,
        json={"parts": list(parts), "title": title, "summary": f"{title}.", "tags": [], "category": None},
    )
    assert response.status_code == 200, response.text
    return response.json()["thought_id"]


def thought_row(url, thought_id) -> Thought:
    return run_db(url, lambda session: session.get(Thought, uuid.UUID(thought_id)))


def linked(url, thought_id):
    proposal_id = thought_row(url, thought_id).proposal_id
    return str(proposal_id) if proposal_id else None


def only_proposal(url, conversation_id) -> str:
    async def work(session):
        rows = await session.execute(
            select(Proposal.id).where(Proposal.conversation_id == uuid.UUID(conversation_id))
        )
        return str(rows.scalar_one())

    return run_db(url, work)


def first_conversation(client, headers) -> str:
    return client.get("/api/conversations", headers=headers).json()["conversations"][0]["id"]


def propose(fake, title):
    thoughts = [{"title": title, "summary": f"{title}.", "tags": [], "category": None}]
    fake.queue(tool_call_chunks("propose_thought", json.dumps({"thoughts": thoughts})), text_chunks("Noted."))


def origin(client, headers, thought_id):
    response = client.get(f"/api/thoughts/{thought_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["origin"]


# --- saving the link (task 2.1) ---


def test_a_confirmed_push_part_stores_its_proposal(client, alice, fake, test_database_url):
    ready_user(client, alice)
    propose(fake, "Oat milk")
    chat(client, alice, "/push buy oat milk")
    conversation_id = first_conversation(client, alice)
    proposal_id = only_proposal(test_database_url, conversation_id)

    thought_id = confirm(client, alice, conversation_id, proposal_id)

    assert linked(test_database_url, thought_id) == proposal_id


def test_a_confirmed_discussion_part_stores_its_proposal(client, alice, fake, conversation_id, test_database_url):
    propose(fake, "Oat milk")
    chat(client, alice, "ok, I'll buy oat milk", conversation_id)
    proposal_id = only_proposal(test_database_url, conversation_id)

    thought_id = confirm(client, alice, conversation_id, proposal_id)

    assert linked(test_database_url, thought_id) == proposal_id


def test_two_parts_of_one_proposal_share_it(client, alice, conversation_id, test_database_url):
    proposal_id = two_parts(test_database_url, conversation_id)

    first = confirm(client, alice, conversation_id, proposal_id, parts=[0])
    second = confirm(client, alice, conversation_id, proposal_id, parts=[1], title="Dentist")

    assert first != second
    assert linked(test_database_url, first) == linked(test_database_url, second) == proposal_id


def test_a_merged_confirm_stores_its_proposal(client, alice, conversation_id, test_database_url):
    proposal_id = two_parts(test_database_url, conversation_id)

    thought_id = confirm(client, alice, conversation_id, proposal_id, parts=[0, 1])

    assert linked(test_database_url, thought_id) == proposal_id


def test_a_thought_stored_otherwise_has_no_proposal(client, alice, fake, test_database_url):
    ready_user(client, alice)

    async def work(session, user, settings, http_client):
        outcome = await store_thought(
            session, user, title="Loose", summary="Stored directly.", settings=settings, http_client=http_client
        )
        return outcome.thought.proposal_id

    assert run_as(test_database_url, user_id_for(client, alice), fake, work) is None


# --- the detail answer (task 2.2) ---


def test_the_origin_names_the_conversation_and_proposal(client, alice, conversation_id, test_database_url):
    proposal_id = two_parts(test_database_url, conversation_id)
    thought_id = confirm(client, alice, conversation_id, proposal_id)
    proposed_at = run_db(test_database_url, lambda s: s.get(Proposal, uuid.UUID(proposal_id))).created_at

    body = origin(client, alice, thought_id)

    assert {k: body[k] for k in ("conversation_id", "conversation_title", "archived", "proposal_id")} == {
        "conversation_id": conversation_id,
        "conversation_title": "Groceries",
        "archived": False,
        "proposal_id": proposal_id,
    }
    assert body["proposed_at"].startswith(proposed_at.date().isoformat())


def test_the_origin_shows_a_rename_and_an_archive(client, alice, conversation_id, test_database_url):
    thought_id = confirm(client, alice, conversation_id, two_parts(test_database_url, conversation_id))

    client.patch(f"/api/conversations/{conversation_id}", headers=alice, json={"title": "Summer trip"})
    renamed = origin(client, alice, thought_id)
    client.patch(f"/api/conversations/{conversation_id}", headers=alice, json={"archived": True})
    archived = origin(client, alice, thought_id)

    assert (renamed["conversation_title"], renamed["archived"]) == ("Summer trip", False)
    assert (archived["conversation_title"], archived["archived"]) == ("Summer trip", True)


def test_no_origin_without_a_proposal_or_after_the_conversation_is_deleted(
    client, alice, fake, conversation_id, test_database_url
):
    thought_id = confirm(client, alice, conversation_id, two_parts(test_database_url, conversation_id))

    async def work(session, user, settings, http_client):
        outcome = await store_thought(
            session, user, title="Loose", summary="Stored directly.", settings=settings, http_client=http_client
        )
        return str(outcome.thought.id)

    loose_id = run_as(test_database_url, user_id_for(client, alice), fake, work)
    assert origin(client, alice, loose_id) is None

    assert client.delete(f"/api/conversations/{conversation_id}", headers=alice).status_code == 204
    assert origin(client, alice, thought_id) is None


@contextmanager
def counted_queries():
    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def test_the_origin_costs_no_more_queries(client, alice, fake, conversation_id, test_database_url):
    thought_id = confirm(client, alice, conversation_id, two_parts(test_database_url, conversation_id))

    async def work(session, user, settings, http_client):
        outcome = await store_thought(
            session, user, title="Loose", summary="Stored directly.", settings=settings, http_client=http_client
        )
        return str(outcome.thought.id)

    loose_id = run_as(test_database_url, user_id_for(client, alice), fake, work)
    origin(client, alice, loose_id)  # warm up

    with counted_queries() as without:
        assert origin(client, alice, loose_id) is None
    with counted_queries() as with_origin:
        assert origin(client, alice, thought_id) is not None

    assert len(with_origin) == len(without)
    assert sum("FROM thoughts" in s for s in with_origin) == 1


# --- deletions (task 1.2) ---


def search_titles(url, user_id, fake, query) -> list[str]:
    async def work(session, user, settings, http_client):
        result = await search_thoughts(session, user, query, settings=settings, http_client=http_client)
        return [hit.thought.title for hit in result.hits]

    return run_as(url, user_id, fake, work)


@pytest.fixture
def bobs_thought(client, bob, fake, test_database_url) -> tuple[str, str]:
    ready_user(client, bob)
    conversation_id = seed_conversation(test_database_url, client, bob)
    proposal_id = seed_proposal(test_database_url, conversation_id, [part(title="Bob's note")])
    return confirm(client, bob, conversation_id, proposal_id, title="Bob's note"), proposal_id


def test_delete_keeps_the_thought_and_clears_only_its_link(
    client, alice, fake, conversation_id, bobs_thought, test_database_url
):
    thought_id = confirm(client, alice, conversation_id, two_parts(test_database_url, conversation_id))
    before = thought_row(test_database_url, thought_id)

    assert client.delete(f"/api/conversations/{conversation_id}", headers=alice).status_code == 204

    after = thought_row(test_database_url, thought_id)
    fields = ("title", "summary", "tags", "category", "raw_text", "created_at")
    assert [getattr(after, f) for f in fields] == [getattr(before, f) for f in fields]
    assert after.proposal_id is None
    assert "Oat milk" in search_titles(test_database_url, user_id_for(client, alice), fake, "Oat milk")
    bobs_id, bobs_proposal = bobs_thought
    assert linked(test_database_url, bobs_id) == bobs_proposal


@pytest.mark.parametrize("path", ["/api/me/content", "/api/me"])
def test_deleting_content_or_the_account_with_linked_thoughts(
    client, alice, conversation_id, bobs_thought, test_database_url, path
):
    proposal_id = two_parts(test_database_url, conversation_id)
    confirm(client, alice, conversation_id, proposal_id, parts=[0])
    confirm(client, alice, conversation_id, proposal_id, parts=[1], title="Dentist")

    assert client.delete(path, headers=alice).status_code == 204

    async def remaining(session):
        return list((await session.execute(select(Thought.title))).scalars())

    assert run_db(test_database_url, remaining) == ["Bob's note"]
    bobs_id, bobs_proposal = bobs_thought
    assert linked(test_database_url, bobs_id) == bobs_proposal
