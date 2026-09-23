"""One user's conversations, messages, and loadout are never visible to or
changed by another user. Usage records are covered with the usage endpoint."""

from app.errors import ErrorCode
from tests.chat_helpers import (
    NANO,
    chat,
    entry,
    error_code,
    ready_user,
    save_models,
    text_chunks,
)
from tests.sse_helpers import parse_events


def alices_conversation(client, alice, fake_llm) -> str:
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi Alice."))
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
    ready_user(client, bob)

    attempts = [
        client.patch(f"/api/conversations/{conversation_id}", headers=bob, json={"title": "mine"}),
        client.patch(f"/api/conversations/{conversation_id}", headers=bob, json={"archived": True}),
        client.delete(f"/api/conversations/{conversation_id}", headers=bob),
        client.post(
            f"/api/conversations/{conversation_id}/proposal/confirm",
            headers=bob,
            json={"title": "t", "summary": "s", "tags": []},
        ),
        chat(client, bob, "add to it", conversation_id),
    ]

    assert [r.status_code for r in attempts] == [404] * len(attempts)
    assert all(error_code(r) == ErrorCode.NOT_FOUND for r in attempts)
    body = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()
    assert body["title"] == "a secret plan"
    assert body["archived"] is False
    assert [m["content"] for m in body["messages"]] == ["a secret plan", "Hi Alice."]


def test_loadout_and_temperature_are_per_user(client, alice, bob, fake_llm):
    ready_user(client, alice)
    save_models(client, alice, entry(NANO, default=True), temperature=1.1)
    ready_user(client, bob)
    save_models(client, bob)

    alices = client.get("/api/settings/models", headers=alice).json()
    assert [m["model"] for m in alices["models"]] == [NANO]
    assert alices["temperature"] == 1.1
    bobs = client.get("/api/settings/models", headers=bob).json()
    assert bobs["models"] == [] and bobs["temperature"] is None
