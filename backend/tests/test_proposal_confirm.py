"""Confirming a proposal saves it (push-and-pull task 4.1), known tags (3.1),
and reading one thought (5.2)."""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import create_engine
from app.models import Conversation, Proposal, Thought, User
from app.routers.conversations import ConfirmIn, confirm_proposal
from app.thoughts.store import known_tags, store_thought
from tests.chat_helpers import (
    MODEL_LIST,
    FakeLLM,
    api_error,
    error_code,
    part,
    run_db,
    save_key,
    seed_conversation,
    seed_proposal,
    user_id_for,
)
from tests.thought_helpers import EMBED_MODEL, models_with_embedding, run_as

pytestmark = pytest.mark.postgres

RAW = "buy oat milk, book the dentist, and idea: a podcast about maps"


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def conversation_id(client, alice, fake, test_database_url) -> str:
    save_key(client, alice)
    return seed_conversation(test_database_url, client, alice)


def three_parts(url, conversation_id, **fields) -> str:
    return seed_proposal(
        url,
        conversation_id,
        [
            part(title="Oat milk", tags=["groceries"], category="task"),
            part(title="Dentist", tags=["health"], category="task"),
            part(title="Map podcast", tags=[], category="idea"),
        ],
        raw_text=RAW,
        **fields,
    )


def confirm(client, headers, conversation_id, proposal_id, **fields):
    body = {
        "parts": [0],
        "title": "Oat milk",
        "summary": "Buy oat milk.",
        "tags": ["groceries"],
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


def proposal_row(url, proposal_id) -> Proposal:
    return run_db(url, lambda session: session.get(Proposal, uuid.UUID(proposal_id)))


def held_id(url, conversation_id):
    async def work(session):
        return (await session.get(Conversation, uuid.UUID(conversation_id))).held_proposal_id

    return run_db(url, work)


def test_the_edited_card_is_stored_with_the_proposals_raw_text(
    client, alice, conversation_id, test_database_url
):
    proposal_id = three_parts(test_database_url, conversation_id)

    response = confirm(
        client, alice, conversation_id, proposal_id,
        parts=[1], title="Book the dentist", summary="Call on Monday.",
        tags=["health", "Calls"], category="decision",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["saved"] is True
    [thought] = thoughts(test_database_url)
    assert body["thought_id"] == str(thought.id)
    assert (thought.title, thought.summary, thought.tags, thought.category, thought.raw_text) == (
        "Book the dentist", "Call on Monday.", ["health", "calls"], "decision", RAW,
    )
    parts = proposal_row(test_database_url, proposal_id).parts
    assert [p["thought_id"] for p in parts] == [None, str(thought.id), None]
    # Two parts wait, so the proposal is still held.
    assert held_id(test_database_url, conversation_id) == uuid.UUID(proposal_id)


def test_confirmed_twice_stores_one_thought_and_answers_its_id(
    client, alice, conversation_id, test_database_url
):
    proposal_id = three_parts(test_database_url, conversation_id)

    first = confirm(client, alice, conversation_id, proposal_id)
    second = confirm(client, alice, conversation_id, proposal_id, title="Changed meanwhile")

    assert first.json()["thought_id"] == second.json()["thought_id"]
    assert [t.title for t in thoughts(test_database_url)] == ["Oat milk"]


def test_two_concurrent_confirms_of_one_part_store_one_thought(
    client, alice, fake, conversation_id, test_database_url
):
    proposal_id = three_parts(test_database_url, conversation_id)
    user_id = uuid.UUID(user_id_for(client, alice))
    body = ConfirmIn(parts=[0], title="Oat milk", summary="Buy oat milk.", tags=[], category=None)

    async def main():
        engine = create_engine(test_database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def one():
            async with sessions() as session:
                user = await session.get(User, user_id)
                return await confirm_proposal(
                    uuid.UUID(conversation_id), uuid.UUID(proposal_id), body, user, session,
                    get_settings(), fake.http_client(),
                )

        try:
            return await asyncio.gather(one(), one())
        finally:
            await engine.dispose()

    first, second = asyncio.run(main())

    assert first.thought_id == second.thought_id
    assert len(thoughts(test_database_url)) == 1


def test_a_merged_confirm_stores_one_thought_and_marks_every_part(
    client, alice, conversation_id, test_database_url
):
    proposal_id = three_parts(test_database_url, conversation_id)

    response = confirm(
        client, alice, conversation_id, proposal_id, parts=[0, 1, 2],
        summary="Buy oat milk.\n\nBook the dentist.\n\nA podcast about maps.",
        tags=["groceries", "health"],
    )

    assert response.status_code == 200, response.text
    [thought] = thoughts(test_database_url)
    parts = proposal_row(test_database_url, proposal_id).parts
    assert [p["thought_id"] for p in parts] == [str(thought.id)] * 3
    assert held_id(test_database_url, conversation_id) is None


def test_a_merge_after_one_part_is_saved_is_refused(
    client, alice, conversation_id, test_database_url
):
    proposal_id = three_parts(test_database_url, conversation_id)
    confirm(client, alice, conversation_id, proposal_id, parts=[2], title="Map podcast")

    response = confirm(client, alice, conversation_id, proposal_id, parts=[0, 1, 2])

    assert response.status_code == 409
    assert error_code(response) == "proposal_part_saved"
    assert len(thoughts(test_database_url)) == 1


def test_a_title_over_200_characters_is_refused_naming_it_and_nothing_is_stored(
    client, alice, conversation_id, test_database_url
):
    proposal_id = three_parts(test_database_url, conversation_id)

    response = confirm(client, alice, conversation_id, proposal_id, title="x" * 201)

    assert response.status_code == 422
    assert response.json()["error"]["message"].startswith("title:")
    assert thoughts(test_database_url) == []
    assert proposal_row(test_database_url, proposal_id).parts[0]["thought_id"] is None


def test_an_unreachable_embedding_provider_still_saves(
    client, alice, fake, conversation_id, test_database_url
):
    proposal_id = three_parts(test_database_url, conversation_id)
    fake.embed_replies.append(api_error(503))

    response = confirm(client, alice, conversation_id, proposal_id)

    assert response.status_code == 200, response.text
    assert [t.title for t in thoughts(test_database_url)] == ["Oat milk"]


def test_another_users_conversation_is_not_found_and_nothing_is_stored(
    client, alice, bob, conversation_id, test_database_url
):
    proposal_id = three_parts(test_database_url, conversation_id)

    response = confirm(client, bob, conversation_id, proposal_id)

    assert response.status_code == 404
    assert error_code(response) == "not_found"
    assert thoughts(test_database_url) == []


def test_the_last_saved_part_clears_the_held_proposal(
    client, alice, conversation_id, test_database_url
):
    proposal_id = seed_proposal(
        test_database_url, conversation_id, [part(title="Oat milk"), part(title="Dentist")]
    )

    confirm(client, alice, conversation_id, proposal_id, parts=[0])
    assert held_id(test_database_url, conversation_id) == uuid.UUID(proposal_id)
    confirm(client, alice, conversation_id, proposal_id, parts=[1], title="Dentist")

    assert held_id(test_database_url, conversation_id) is None


def test_a_replaced_proposals_card_still_saves(client, alice, conversation_id, test_database_url):
    older = seed_proposal(test_database_url, conversation_id, [part(title="Oat milk")], raw_text="older")
    newer = seed_proposal(test_database_url, conversation_id, [part(title="Eggs")], position=3)

    response = confirm(client, alice, conversation_id, older)

    assert response.status_code == 200, response.text
    [thought] = thoughts(test_database_url)
    assert thought.raw_text == "older"
    # The newer proposal stays held.
    assert held_id(test_database_url, conversation_id) == uuid.UUID(newer)


def test_a_reopened_conversation_lists_its_proposals_with_their_saved_state(
    client, alice, bob, conversation_id, test_database_url
):
    later = seed_proposal(test_database_url, conversation_id, [part(title="Eggs")], position=5)
    earlier = three_parts(test_database_url, conversation_id, position=1)
    thought_id = confirm(client, alice, conversation_id, earlier, parts=[1]).json()["thought_id"]

    body = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()

    assert [p["id"] for p in body["proposals"]] == [earlier, later]
    assert [p["position"] for p in body["proposals"]] == [1, 5]
    assert [part["thought_id"] for part in body["proposals"][0]["parts"]] == [None, thought_id, None]
    assert client.get(f"/api/conversations/{conversation_id}", headers=bob).status_code == 404


# --- known tags (design decision 6) ---


def store(url, user_id, fake, title, tags):
    async def work(session, user, settings, http_client):
        await store_thought(
            session, user, title=title, summary=title, tags=tags, settings=settings, http_client=http_client
        )

    run_as(url, user_id, fake, work)


def test_known_tags_come_most_used_first_and_stop_at_the_limit(
    client, alice, bob, fake, test_database_url
):
    save_key(client, alice)
    alice_id = user_id_for(client, alice)
    bob_id = user_id_for(client, bob)
    store(test_database_url, alice_id, fake, "Oat milk", ["groceries", "milk"])
    store(test_database_url, alice_id, fake, "Eggs", ["groceries", "breakfast"])
    store(test_database_url, alice_id, fake, "Bread", ["groceries", "breakfast", "bakery"])
    store(test_database_url, bob_id, fake, "Bob's", ["bob-only"])

    async def tags(session, user, settings, http_client):
        return await known_tags(session, user, 3), await known_tags(session, user, 40)

    top, every = run_as(test_database_url, alice_id, fake, tags)

    assert top == ["groceries", "breakfast", "bakery"]
    assert every == ["groceries", "breakfast", "bakery", "milk"]


def test_known_tags_reach_the_proposal_tool(client, alice, fake, test_database_url):
    from tests.chat_helpers import chat, entry, NANO, save_models, text_chunks

    save_key(client, alice)
    save_models(client, alice, entry(NANO, default=True))
    user_id = user_id_for(client, alice)
    store(test_database_url, user_id, fake, "Oat milk", ["groceries"])
    fake.queue(text_chunks("Hi."))

    chat(client, alice, "hello")

    [tool] = [t for t in fake.chat_requests[0]["tools"] if t["function"]["name"] == "propose_thought"]
    tags = tool["function"]["parameters"]["properties"]["thoughts"]["items"]["properties"]["tags"]
    assert tags["description"].endswith("Reuse one of the user's tags where it fits: groceries.")


# --- one thought (task 5.2) ---


def test_the_owner_reads_every_field_and_others_get_not_found(
    client, alice, bob, fake, conversation_id, test_database_url
):
    proposal_id = three_parts(test_database_url, conversation_id)
    thought_id = confirm(client, alice, conversation_id, proposal_id).json()["thought_id"]

    response = client.get(f"/api/thoughts/{thought_id}", headers=alice)

    assert response.status_code == 200
    body = response.json()
    assert {k: body[k] for k in ("id", "title", "summary", "tags", "category", "raw_text")} == {
        "id": thought_id,
        "title": "Oat milk",
        "summary": "Buy oat milk.",
        "tags": ["groceries"],
        "category": "task",
        "raw_text": RAW,
    }
    assert body["created_at"] and body["updated_at"]

    foreign = client.get(f"/api/thoughts/{thought_id}", headers=bob)
    unknown = client.get(f"/api/thoughts/{uuid.uuid4()}", headers=alice)
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()
    assert error_code(foreign) == "not_found"

