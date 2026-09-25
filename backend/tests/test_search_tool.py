"""The search tool through the chat endpoint (thought-storage task 6.2)."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update

from app.chat.tools import NO_MATCH
from app.models import Thought, UsageEvent
from app.thoughts.store import store_thought
from tests.chat_helpers import (
    NANO,
    chat,
    entry,
    ready_user,
    run_db,
    save_models,
    text_chunks,
    tool_call_chunks,
    user_id_for,
)
from tests.sse_helpers import parse_events
from tests.thought_helpers import run_as

pytestmark = pytest.mark.postgres


def events_of(response, name: str) -> list[dict]:
    return [data for event, data in parse_events(response.text) if event == name]


def store(url, user_id, fake, title, summary, created=None, **fields):
    async def work(session, user, settings, http_client):
        outcome = await store_thought(
            session, user, title=title, summary=summary, settings=settings,
            http_client=http_client, **fields,
        )
        if created is not None:
            await session.execute(
                update(Thought).where(Thought.id == outcome.thought.id).values(created_at=created)
            )
            await session.commit()
        return str(outcome.thought.id)

    return run_as(url, user_id, fake, work)


def search_in_chat(client, headers, fake_llm, arguments: dict, message="what did I file?"):
    fake_llm.queue(
        tool_call_chunks("search_thoughts", json.dumps(arguments)), text_chunks("Here it is.")
    )
    response = chat(client, headers, message)
    tool_result = fake_llm.chat_requests[-1]["messages"][-1]
    assert tool_result["role"] == "tool"
    return response, tool_result["content"]


def stored_tool_details(client, headers) -> list:
    conversation_id = client.get("/api/conversations", headers=headers).json()["conversations"][0]["id"]
    messages = client.get(f"/api/conversations/{conversation_id}", headers=headers).json()["messages"]
    return [m["details"] for m in messages if m["role"] == "tool"]


def test_result_has_the_documented_form_and_sources_go_in_the_event_and_the_message(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    thought_id = store(
        test_database_url, user_id, fake_llm, "Oat milk", "Buy oat milk on the way home.",
        created=datetime(2026, 9, 20, tzinfo=UTC), tags=["groceries"],
    )
    other_id = store(
        test_database_url, user_id, fake_llm, "Shopping list", "Milk, bread, eggs.",
        created=datetime(2026, 9, 21, tzinfo=UTC), tags=["shopping"],
    )

    response, content = search_in_chat(client, alice, fake_llm, {"query": "oat milk"})

    assert content.startswith("2 of your thoughts match (best first):\n")
    assert "1. Oat milk · 2026-09-20 · #groceries\n   Buy oat milk on the way home." in content
    assert thought_id not in content and other_id not in content
    [end] = [e for e in events_of(response, "tool") if e["phase"] == "end"]
    assert end["sources"] == [
        {"id": thought_id, "title": "Oat milk", "created_at": "2026-09-20T00:00:00+00:00", "tags": ["groceries"]},
        {"id": other_id, "title": "Shopping list", "created_at": "2026-09-21T00:00:00+00:00", "tags": ["shopping"]},
    ]
    assert stored_tool_details(client, alice) == [{"sources": end["sources"]}]
    assert events_of(response, "done")


def test_tags_and_since_narrow_the_search(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    store(test_database_url, user_id, fake_llm, "Work plans", "Plans for the roadmap.",
          created=datetime(2026, 9, 10, tzinfo=UTC), tags=["work"])
    store(test_database_url, user_id, fake_llm, "Old work plans", "Plans for last quarter.",
          created=datetime(2026, 8, 1, tzinfo=UTC), tags=["work"])
    store(test_database_url, user_id, fake_llm, "Holiday plans", "Plans for the trip.",
          created=datetime(2026, 9, 12, tzinfo=UTC), tags=["travel"])

    _, content = search_in_chat(
        client, alice, fake_llm, {"query": "plans", "tags": ["work"], "since": "2026-09-01"}
    )

    assert "Work plans" in content
    assert "Old work plans" not in content and "Holiday plans" not in content


def test_malformed_since_is_a_tool_argument_error(client, alice, fake_llm):
    ready_user(client, alice)
    _, content = search_in_chat(client, alice, fake_llm, {"query": "x", "since": "last week"})
    assert content.startswith("Error: since must be a date written YYYY-MM-DD.")


def test_no_thoughts_gives_no_match(client, alice, fake_llm):
    ready_user(client, alice)
    _, content = search_in_chat(client, alice, fake_llm, {"query": "milk"})
    assert content == NO_MATCH


def test_no_match(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    store(test_database_url, user_id, fake_llm, "Oat milk", "Buy oat milk on the way home.")
    response, content = search_in_chat(client, alice, fake_llm, {"query": "quantum physics"})
    assert content == NO_MATCH
    [end] = [e for e in events_of(response, "tool") if e["phase"] == "end"]
    assert end["sources"] == []
    assert stored_tool_details(client, alice) == [{"sources": []}]


def test_missing_key_searches_by_words_and_the_turn_ends_normally(
    client, bob, fake_llm, test_database_url
):
    # Bob chats with a local model that needs no key, and has no Nebius key
    # for embeddings.
    response = save_models(client, bob, entry(NANO, provider_id="local", default=True))
    assert response.status_code == 200, response.text
    user_id = user_id_for(client, bob)
    store(test_database_url, user_id, fake_llm, "Oat milk", "Buy oat milk on the way home.")

    response, content = search_in_chat(client, bob, fake_llm, {"query": "oat"})

    assert "Oat milk" in content
    assert content.splitlines()[-1] == (
        "Searched by words only: add your Nebius Token Factory API key in settings to also "
        "search by meaning. Tell the user."
    )
    assert events_of(response, "done") and not events_of(response, "error")


def test_embedding_usage_carries_the_conversation(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    store(test_database_url, user_id, fake_llm, "Oat milk", "Buy oat milk on the way home.")

    response, _ = search_in_chat(client, alice, fake_llm, {"query": "milk"})
    conversation_id = events_of(response, "conversation")[0]["id"]

    async def embed_events(session):
        query = select(UsageEvent).where(
            UsageEvent.user_id == uuid.UUID(user_id), UsageEvent.kind == "embed"
        )
        return list((await session.execute(query)).scalars())

    events = run_db(test_database_url, embed_events)
    in_chat = [event for event in events if event.conversation_id is not None]
    assert [str(event.conversation_id) for event in in_chat] == [conversation_id]
