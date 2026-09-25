"""Proposals: the held note, the forced call, time, and the raw text (push-and-pull 3.2)."""

import json
import uuid

from sqlalchemy import select

from app.chat.prompt import build_context, held_proposal_note, system_prompt
from app.models import Conversation, Message, Proposal
from tests.chat_helpers import (
    chat,
    completion,
    error_code,
    part,
    ready_user,
    run_db,
    seed_conversation,
    seed_proposal,
    text_chunks,
    tool_call,
    tool_call_chunks,
)
from tests.sse_helpers import parse_events

PROPOSAL = {"title": "Oat milk", "summary": "Buy oat milk tomorrow.", "tags": ["shopping"], "category": "task"}
PARTS = [part()]


def stored(client, headers, conversation_id) -> dict:
    return client.get(f"/api/conversations/{conversation_id}", headers=headers).json()


def offer(client, headers, conversation_id):
    return client.post(f"/api/conversations/{conversation_id}/proposal", headers=headers)


def system_notes(request: dict) -> list[str]:
    return [m["content"] for m in request["messages"] if m["role"] == "system"]


def proposals(url, conversation_id) -> list[Proposal]:
    async def work(session):
        rows = await session.execute(
            select(Proposal)
            .where(Proposal.conversation_id == uuid.UUID(conversation_id))
            .order_by(Proposal.position)
        )
        return list(rows.scalars())

    return run_db(url, work)


def held_id(url, conversation_id):
    async def work(session):
        return (await session.get(Conversation, uuid.UUID(conversation_id))).held_proposal_id

    return run_db(url, work)


def proposal_events(response) -> list[dict]:
    return [data for name, data in parse_events(response.text) if name == "proposal"]


# --- the held-proposal note ---


def test_the_note_follows_the_latest_message_when_a_proposal_is_held():
    user = Message(position=0, role="user", content="hi", compacted=False)
    context = build_context([user], PARTS)
    assert context[0] == {"role": "system", "content": system_prompt()}
    assert context[1] == {"role": "user", "content": "hi"}
    assert context[2] == {"role": "system", "content": held_proposal_note(PARTS)}
    note = context[2]["content"]
    assert "Oat milk" in note and "Buy oat milk tomorrow." in note and "shopping" in note
    assert "Category: task" in note
    assert "Do not propose it again" in note and "something else" in note
    assert "delet" not in note.lower()


def test_the_note_lists_only_parts_not_saved():
    parts = [part(title="Oat milk", thought_id=str(uuid.uuid4())), part(title="Dentist")]
    note = held_proposal_note(parts)
    assert "Dentist" in note
    assert "Oat milk" not in note


def test_there_is_no_note_without_a_held_proposal_or_with_every_part_saved():
    user = Message(position=0, role="user", content="hi", compacted=False)
    plain = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": "hi"},
    ]
    assert build_context([user]) == plain
    assert build_context([user], [part(thought_id=str(uuid.uuid4()))]) == plain


def test_a_turn_with_a_held_proposal_sends_the_note_and_keeps_it_held(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    proposal_id = seed_proposal(test_database_url, conversation_id, PARTS)
    fake_llm.queue(text_chunks("Sure."), text_chunks("Still here."))

    chat(client, alice, "and also soy milk?", conversation_id)
    chat(client, alice, "ok thanks", conversation_id)

    for request in fake_llm.chat_requests:
        assert system_notes(request)[1] == held_proposal_note(PARTS)
    assert stored(client, alice, conversation_id)["held_proposal_id"] == proposal_id


def test_a_new_topic_replaces_the_held_proposal(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    old_id = seed_proposal(test_database_url, conversation_id, PARTS)
    wider = {"thoughts": [{"title": "Groceries", "summary": "Oat and soy milk.", "tags": ["shopping"], "category": "task"}]}
    fake_llm.queue(tool_call_chunks("propose_thought", json.dumps(wider)), text_chunks("Now, taxes."))

    response = chat(client, alice, "unrelated: how do taxes work?", conversation_id)

    [event] = proposal_events(response)
    assert event["parts"][0]["title"] == "Groceries"
    assert event["replaces"] == old_id
    body = stored(client, alice, conversation_id)
    assert body["held_proposal_id"] == event["id"] != old_id
    # The replaced card is kept, marked with what replaced it.
    replaced = {p["id"]: p["replaced_by"] for p in body["proposals"]}
    assert replaced == {old_id: event["id"], event["id"]: None}
    # The note has done its job: the next round answers without it.
    first, second = fake_llm.chat_requests
    assert held_proposal_note(PARTS) in system_notes(first)
    assert system_notes(second) == [system_prompt()]


# --- the forced proposal call ---


def test_the_forced_call_returns_and_holds_a_proposal(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=("I must buy oat milk", "Noted.")
    )
    fake_llm.queue(completion(None, tool_calls=[tool_call("propose_thought", {"thoughts": [PROPOSAL]})]))

    response = offer(client, alice, conversation_id)

    assert response.status_code == 200, response.text
    offered = response.json()["proposal"]
    assert offered["parts"] == [{**PROPOSAL, "thought_id": None}]
    assert offered["position"] == 1
    request = fake_llm.chat_requests[0]
    assert request["tool_choice"] == {"type": "function", "function": {"name": "propose_thought"}}
    assert "stream" not in request
    body = stored(client, alice, conversation_id)
    assert body["held_proposal_id"] == offered["id"]
    assert len(body["messages"]) == 2
    [row] = proposals(test_database_url, conversation_id)
    assert row.raw_text == "I must buy oat milk"


def test_the_forced_call_is_not_made_when_a_proposal_is_held(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    proposal_id = seed_proposal(test_database_url, conversation_id, PARTS)

    response = offer(client, alice, conversation_id)

    assert response.json()["proposal"]["id"] == proposal_id
    assert fake_llm.chat_requests == []


def test_an_offer_with_one_part_saved_keeps_both_parts_with_their_state(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    saved = str(uuid.uuid4())
    seed_proposal(
        test_database_url, conversation_id, [part(title="Oat milk", thought_id=saved), part(title="Dentist")]
    )

    parts = offer(client, alice, conversation_id).json()["proposal"]["parts"]

    assert [(p["title"], p["thought_id"]) for p in parts] == [("Oat milk", saved), ("Dentist", None)]
    assert fake_llm.chat_requests == []


def test_a_held_proposal_with_every_part_saved_is_not_offered(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    seed_proposal(test_database_url, conversation_id, [part(thought_id=str(uuid.uuid4()))])
    fake_llm.queue(completion(None, tool_calls=[tool_call("propose_thought", {"thoughts": [PROPOSAL]})]))

    offered = offer(client, alice, conversation_id).json()["proposal"]

    assert len(fake_llm.chat_requests) == 1
    assert offered["parts"][0]["thought_id"] is None


def test_a_conversation_without_a_discussion_has_nothing_to_offer(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice, messages=())

    assert offer(client, alice, conversation_id).json() == {"proposal": None}
    assert fake_llm.chat_requests == []


def test_arguments_that_do_not_fit_offer_nothing(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    fake_llm.queue(completion(None, tool_calls=[tool_call("propose_thought", {"title": ""})]))

    assert offer(client, alice, conversation_id).json() == {"proposal": None}
    assert stored(client, alice, conversation_id)["held_proposal_id"] is None
    assert proposals(test_database_url, conversation_id) == []


def test_the_forced_call_releases_the_conversation(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    fake_llm.queue(
        completion(None, tool_calls=[tool_call("propose_thought", {"thoughts": [PROPOSAL]})]),
        text_chunks("Hi."),
    )

    offer(client, alice, conversation_id)

    assert chat(client, alice, "more", conversation_id).status_code == 200


def test_another_users_conversation_has_no_proposal_to_offer(
    client, alice, bob, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    seed_proposal(test_database_url, conversation_id, PARTS)

    response = offer(client, bob, conversation_id)

    assert response.status_code == 404
    assert error_code(response) == "not_found"


# --- time never brings a held proposal back ---


def test_an_old_conversation_shows_its_proposal_only_as_held(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice, minutes_ago=60 * 24 * 90)
    proposal_id = seed_proposal(test_database_url, conversation_id, PARTS)

    body = stored(client, alice, conversation_id)
    client.get("/api/conversations", headers=alice)

    assert body["held_proposal_id"] == proposal_id
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert fake_llm.chat_requests == []


# --- the raw text (design decision 3) ---


def propose(fake_llm, *titles):
    thoughts = [{"title": t, "summary": f"{t}.", "tags": [], "category": "note"} for t in titles]
    fake_llm.queue(
        tool_call_chunks("propose_thought", json.dumps({"thoughts": thoughts})), text_chunks("Noted.")
    )


def first_conversation(client, headers) -> str:
    return client.get("/api/conversations", headers=headers).json()["conversations"][0]["id"]


def test_push_keeps_the_message_without_its_command(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hello."))
    chat(client, alice, "earlier talk")
    conversation_id = first_conversation(client, alice)
    propose(fake_llm, "Oat milk")

    chat(client, alice, "/push buy oat milk", conversation_id)

    [row] = proposals(test_database_url, conversation_id)
    assert row.raw_text == "buy oat milk"
    assert (row.from_position, row.to_position) == (2, 2)


def test_a_discussion_keeps_only_the_users_messages_in_order(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        messages=("Rust or Go for the CLI?", "Rust is fast to start.", "/explore and for services?", "Go is simple."),
    )
    propose(fake_llm, "Languages")

    chat(client, alice, "ok I've decided: Rust for the CLI, Go for the services", conversation_id)

    [row] = proposals(test_database_url, conversation_id)
    assert row.raw_text == (
        "Rust or Go for the CLI?\n\nand for services?\n\n"
        "ok I've decided: Rust for the CLI, Go for the services"
    )
    assert (row.from_position, row.to_position) == (0, 4)


def test_a_second_discussion_starts_after_the_last_saved_proposal(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        messages=("first topic", "Ok.", "first decided", "Noted.", "second topic", "Ok.", "more on it", "Sure."),
    )
    # A saved proposal ends the first discussion at message 2; an unsaved one
    # after it does not end anything.
    seed_proposal(
        test_database_url, conversation_id, [part(thought_id=str(uuid.uuid4()))],
        position=3, from_position=0, to_position=2, hold=False,
    )
    seed_proposal(
        test_database_url, conversation_id, [part()], position=5, from_position=4, to_position=4
    )
    propose(fake_llm, "Second")

    chat(client, alice, "second decided", conversation_id)

    row = proposals(test_database_url, conversation_id)[-1]
    assert row.raw_text == "second topic\n\nmore on it\n\nsecond decided"


def test_compacted_messages_count_and_summaries_do_not(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=("old point", "Ok.", "newer point", "Sure.")
    )

    async def compact(session):
        rows = await session.execute(
            select(Message).where(Message.conversation_id == uuid.UUID(conversation_id), Message.position < 2)
        )
        for message in rows.scalars():
            message.compacted = True
        session.add(
            Message(
                conversation_id=uuid.UUID(conversation_id), position=4, role="summary",
                content="The user made an old point.",
            )
        )
        await session.commit()

    run_db(test_database_url, compact)
    propose(fake_llm, "Points")

    chat(client, alice, "that is all", conversation_id)

    [row] = proposals(test_database_url, conversation_id)
    assert row.raw_text == "old point\n\nnewer point\n\nthat is all"


def test_a_long_discussion_keeps_the_most_recent_whole_messages(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    long = "x" * 9_000
    conversation_id = seed_conversation(
        test_database_url, client, alice,
        messages=("a" * 9_000, "Ok.", "b" * 9_000, "Ok.", long, "Ok."),
    )
    propose(fake_llm, "Long")

    chat(client, alice, "decided", conversation_id)

    [row] = proposals(test_database_url, conversation_id)
    assert row.raw_text == "b" * 9_000 + "\n\n" + long + "\n\ndecided"
    assert row.from_position == 2
    assert len(row.raw_text) <= 20_000


def test_a_single_message_over_the_limit_is_cut_at_its_end(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hello."))
    chat(client, alice, "hello")
    conversation_id = first_conversation(client, alice)
    propose(fake_llm, "Huge")

    chat(client, alice, "/push " + "y" * 25_000, conversation_id)

    [row] = proposals(test_database_url, conversation_id)
    assert row.raw_text == "y" * 20_000


def test_a_proposal_with_every_part_saved_is_not_marked_replaced(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    old_id = seed_proposal(test_database_url, conversation_id, [part(thought_id=str(uuid.uuid4()))])
    propose(fake_llm, "Next")

    response = chat(client, alice, "something new", conversation_id)

    [event] = proposal_events(response)
    assert event["replaces"] is None
    replaced = {p["id"]: p["replaced_by"] for p in stored(client, alice, conversation_id)["proposals"]}
    assert replaced[old_id] is None
