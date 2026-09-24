"""The held proposal: the note in the context, the forced call, and time."""

import json

from app.chat.prompt import system_prompt, build_context, held_proposal_note
from app.models import Message
from tests.chat_helpers import (
    chat,
    completion,
    error_code,
    ready_user,
    seed_conversation,
    text_chunks,
    tool_call,
    tool_call_chunks,
)

PROPOSAL = {"title": "Oat milk", "summary": "Buy oat milk tomorrow.", "tags": ["shopping"]}
HELD = {**PROPOSAL, "position": 1}


def stored(client, headers, conversation_id) -> dict:
    return client.get(f"/api/conversations/{conversation_id}", headers=headers).json()


def offer(client, headers, conversation_id):
    return client.post(f"/api/conversations/{conversation_id}/proposal", headers=headers)


def system_notes(request: dict) -> list[str]:
    return [m["content"] for m in request["messages"] if m["role"] == "system"]


# --- 7.5 the held-proposal note ---


def test_the_note_follows_the_latest_message_when_a_proposal_is_held():
    user = Message(position=0, role="user", content="hi", compacted=False)
    context = build_context([user], HELD)
    assert context[0] == {"role": "system", "content": system_prompt()}
    assert context[1] == {"role": "user", "content": "hi"}
    assert context[2] == {"role": "system", "content": held_proposal_note(HELD)}
    note = context[2]["content"]
    assert "Oat milk" in note and "Buy oat milk tomorrow." in note and "shopping" in note
    assert "Do not propose it again" in note and "something else" in note
    assert "delet" not in note.lower()


def test_there_is_no_note_without_a_held_proposal():
    user = Message(position=0, role="user", content="hi", compacted=False)
    assert build_context([user]) == [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": "hi"},
    ]


def test_a_turn_with_a_held_proposal_sends_the_note_and_keeps_it_held(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice, held_proposal=HELD)
    fake_llm.queue(text_chunks("Sure."), text_chunks("Still here."))

    chat(client, alice, "and also soy milk?", conversation_id)
    chat(client, alice, "ok thanks", conversation_id)

    for request in fake_llm.chat_requests:
        assert system_notes(request)[1] == held_proposal_note(HELD)
    assert stored(client, alice, conversation_id)["held_proposal"] == HELD


def test_a_new_topic_replaces_the_held_proposal(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice, held_proposal=HELD)
    wider = {"title": "Groceries", "summary": "Oat and soy milk.", "tags": ["shopping"]}
    fake_llm.queue(tool_call_chunks("propose_thought", json.dumps(wider)), text_chunks("Now, taxes."))

    response = chat(client, alice, "unrelated: how do taxes work?", conversation_id)

    assert '"title": "Groceries"' in response.text
    assert stored(client, alice, conversation_id)["held_proposal"]["title"] == "Groceries"
    # The note has done its job: the next round answers without it.
    first, second = fake_llm.chat_requests
    assert held_proposal_note(HELD) in system_notes(first)
    assert system_notes(second) == [system_prompt()]


# --- 7.6 the forced proposal call ---


def test_the_forced_call_returns_and_holds_a_proposal(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=("I must buy oat milk", "Noted.")
    )
    fake_llm.queue(completion(None, tool_calls=[tool_call("propose_thought", PROPOSAL)]))

    response = offer(client, alice, conversation_id)

    assert response.status_code == 200, response.text
    assert response.json() == {"held_proposal": HELD}
    request = fake_llm.chat_requests[0]
    assert request["tool_choice"] == {"type": "function", "function": {"name": "propose_thought"}}
    assert "stream" not in request
    body = stored(client, alice, conversation_id)
    assert body["held_proposal"] == HELD
    assert len(body["messages"]) == 2


def test_the_forced_call_is_not_made_when_a_proposal_is_held(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice, held_proposal=HELD)

    response = offer(client, alice, conversation_id)

    assert response.json() == {"held_proposal": HELD}
    assert fake_llm.chat_requests == []


def test_a_conversation_without_a_discussion_has_nothing_to_offer(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice, messages=())

    assert offer(client, alice, conversation_id).json() == {"held_proposal": None}
    assert fake_llm.chat_requests == []


def test_arguments_that_do_not_fit_offer_nothing(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    fake_llm.queue(completion(None, tool_calls=[tool_call("propose_thought", {"title": ""})]))

    assert offer(client, alice, conversation_id).json() == {"held_proposal": None}
    assert stored(client, alice, conversation_id)["held_proposal"] is None


def test_the_forced_call_releases_the_conversation(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    fake_llm.queue(
        completion(None, tool_calls=[tool_call("propose_thought", PROPOSAL)]), text_chunks("Hi.")
    )

    offer(client, alice, conversation_id)

    assert chat(client, alice, "more", conversation_id).status_code == 200


def test_another_users_conversation_has_no_proposal_to_offer(
    client, alice, bob, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice, held_proposal=HELD)

    response = offer(client, bob, conversation_id)

    assert response.status_code == 404
    assert error_code(response) == "not_found"


# --- 7.7 time never brings a held proposal back ---


def test_an_old_conversation_shows_its_proposal_only_as_held(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(
        test_database_url, client, alice, minutes_ago=60 * 24 * 90, held_proposal=HELD
    )

    body = stored(client, alice, conversation_id)
    client.get("/api/conversations", headers=alice)

    assert body["held_proposal"] == HELD
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert fake_llm.chat_requests == []
