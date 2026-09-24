"""One user's conversations, messages, usage, and loadout are never visible to
or changed by another user. Reading another user's usage is covered in
test_usage.py."""

import uuid

from sqlalchemy import select

from app.errors import ErrorCode
from app.models import UsageEvent
from tests.chat_helpers import (
    BIG,
    NANO,
    chat,
    entry,
    error_code,
    ready_user,
    run_db,
    save_models,
    text_chunks,
    usage_chunk,
    user_id_for,
)
from tests.sse_helpers import parse_events


def alices_conversation(client, alice, fake_llm) -> str:
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi Alice.") + [usage_chunk(100, 20)])
    events = parse_events(chat(client, alice, "a secret plan").text)
    return events[0][1]["id"]


def test_conversations_and_messages_are_invisible_to_another_user(client, alice, bob, fake_llm):
    conversation_id = alices_conversation(client, alice, fake_llm)

    lists = client.get("/api/conversations", headers=bob).json()
    assert lists == {"conversations": [], "archived": []}
    response = client.get(f"/api/conversations/{conversation_id}", headers=bob)
    assert response.status_code == 404
    assert "secret" not in response.text


def test_another_user_cannot_change_or_delete_a_conversation(client, alice, bob, fake_llm):
    conversation_id = alices_conversation(client, alice, fake_llm)
    ready_user(client, bob, entry(NANO, default=True), entry(BIG))
    model_calls = len(fake_llm.chat_requests)

    attempts = [
        client.patch(f"/api/conversations/{conversation_id}", headers=bob, json={"title": "mine"}),
        client.patch(f"/api/conversations/{conversation_id}", headers=bob, json={"archived": True}),
        client.patch(
            f"/api/conversations/{conversation_id}",
            headers=bob,
            json={"provider_id": "nebius", "model": BIG},
        ),
        client.post(
            f"/api/conversations/{conversation_id}/compaction",
            headers=bob,
            json={"summary": "bob's summary", "through_position": 0},
        ),
        client.post(f"/api/conversations/{conversation_id}/proposal", headers=bob),
        chat(client, bob, "/compact", conversation_id),
        client.delete(f"/api/conversations/{conversation_id}", headers=bob),
        client.post(
            f"/api/conversations/{conversation_id}/proposals/{uuid.uuid4()}/confirm",
            headers=bob,
            json={"parts": [0], "title": "t", "summary": "s", "tags": []},
        ),
        chat(client, bob, "add to it", conversation_id),
    ]

    assert [r.status_code for r in attempts] == [404] * len(attempts)
    assert all(error_code(r) == ErrorCode.NOT_FOUND for r in attempts)
    body = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()
    assert body["title"] == "a secret plan"
    assert body["archived"] is False
    assert body["model"] == NANO
    assert body["held_proposal_id"] is None
    assert body["proposals"] == []
    assert [m["content"] for m in body["messages"]] == ["a secret plan", "Hi Alice."]
    assert not any(m["compacted"] for m in body["messages"])
    assert len(fake_llm.chat_requests) == model_calls


def test_usage_records_stay_with_their_user(client, alice, bob, fake_llm, test_database_url):
    conversation_id = alices_conversation(client, alice, fake_llm)
    ready_user(client, bob)
    fake_llm.queue(text_chunks("Hi Bob.") + [usage_chunk(300, 30)])
    chat(client, bob, "hello")
    client.delete(f"/api/conversations/{conversation_id}", headers=bob)

    async def rows(session):
        events = (await session.execute(select(UsageEvent))).scalars().all()
        return {(str(e.user_id), e.prompt_tokens) for e in events}

    assert run_db(test_database_url, rows) == {
        (user_id_for(client, alice), 100),
        (user_id_for(client, bob), 300),
    }
    alices = client.get("/api/usage", headers=alice).json()
    assert [m["tokens"] for m in alices["by_model"]] == [120]


def test_loadout_and_temperature_are_per_user(client, alice, bob, fake_llm):
    ready_user(client, alice)
    client.put(
        "/api/settings/models",
        headers=alice,
        json={
            "models": [entry(NANO, default=True)],
            "temperature": 1.1,
            "warning": {"unit": "usd", "amount": "5"},
        },
    )
    ready_user(client, bob)
    save_models(client, bob)

    alices = client.get("/api/settings/models", headers=alice).json()
    assert [m["model"] for m in alices["models"]] == [NANO]
    assert alices["temperature"] == 1.1
    assert alices["warning"] == {"unit": "usd", "amount": 5.0}
    bobs = client.get("/api/settings/models", headers=bob).json()
    assert bobs["models"] == [] and bobs["temperature"] is None
    assert bobs["warning"] is None
