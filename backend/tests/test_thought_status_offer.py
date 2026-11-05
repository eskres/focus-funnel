"""Marks in the offer, in the filed test, in the held proposal, and the done
marker in the notes the model reads (thought-status tasks 3.5 to 3.7).

On SQLite, with the fakes from tests/status_fakes.py.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.chat import proposal as proposal_module
from app.chat.config import get_chat_config
from app.chat.conversations import list_messages
from app.chat.prompt import OFFER_NOTE, held_proposal_note, unsaved_parts
from app.chat.proposal import (
    discussion_start,
    held_parts,
    list_proposals,
    raw_text_for,
    write_proposal,
)
from app.chat.refs import saved_ids
from app.chat.similar import REPEATED_TASK
from app.models import Conversation
from tests import test_thought_status_turn as turn_tests
from tests.chat_helpers import (
    chat,
    completion,
    part,
    run_db,
    seed_conversation,
    seed_proposal,
    text_chunks,
    tool_call,
)
from tests.status_fakes import fake_similar, seed_active_index
from tests.test_thought_refs import refs_of, seed_thought, seed_tool
from tests.test_thought_status_turn import (
    HELD_HEAD,
    OAT_MILK,
    mark_done,
    milk,
    plumber,
    propose,
    rows,
    seen_conversation,
    status_part,
    system_notes,
    tool_results,
)
from tests.thought_helpers import counted_queries

fake = turn_tests.fake
alice_id = turn_tests.alice_id

DONE_DAY = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
# Small talk first, so /compact (which keeps the 6 most recent) has
# something to compact.
EARLIER = ("hi", "Hello!", "how are you?", "Fine, thanks.", "good", "Great.")


def offer(client, headers, conversation_id):
    return client.post(f"/api/conversations/{conversation_id}/proposal", headers=headers)


def go_ahead(client, headers, conversation_id, action, fake) -> int:
    """The action the offer came before: /compact (a summary draft) or archive."""
    if action == "compact":
        fake.queue(text_chunks("Summary of the talk."))
        return chat(client, headers, "/compact", conversation_id).status_code
    return client.patch(
        f"/api/conversations/{conversation_id}", headers=headers, json={"archived": True}
    ).status_code


def asked(arguments: dict) -> dict:
    return completion(None, tool_calls=[tool_call("propose_thought", arguments)])


def propose_tool(request: dict) -> dict:
    [tool] = [t for t in request["tools"] if t["function"]["name"] == "propose_thought"]
    return tool


def spy(monkeypatch) -> dict:
    """Record what write_proposal() gets from the offer, and fail on any mark check."""
    seen: dict = {"parts": []}
    original = proposal_module.write_proposal

    async def recording(session, conversation, parts, position, **options):
        seen["parts"].append(parts)
        return await original(session, conversation, parts, position, **options)

    async def no_marks(*args, **kwargs):
        raise AssertionError("the offer checked a mark")

    monkeypatch.setattr(proposal_module, "write_proposal", recording)
    monkeypatch.setattr(proposal_module, "resolve_marks", no_marks)
    return seen


def mark_check_statements(statements: list[str]) -> list[str]:
    return [s for s in statements if s.lstrip().startswith("SELECT thoughts.id, thoughts.status")]


@pytest.fixture
def talk(client, alice, test_database_url, fake, alice_id, monkeypatch):
    """A conversation that saw the open task Call the plumber (T1), then talked."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        messages=(
            *EARLIER,
            "what is open?",
            "The plumber task.",
            "I called him, and I need oat milk",
            "Noted.",
        ),
    )
    seed_tool(test_database_url, conversation_id, 10, sources=[task])
    seed_active_index(test_database_url, alice_id)
    lookups = fake_similar(monkeypatch, {})
    return task, conversation_id, lookups


# --- 3.5: the offer ignores every mark ---


@pytest.mark.parametrize("action", ["compact", "archive"])
def test_a_call_with_only_a_mark_offers_nothing_and_the_action_goes_ahead(
    client, alice, test_database_url, fake, talk, monkeypatch, action
):
    _, conversation_id, lookups = talk
    seen = spy(monkeypatch)
    fake.queue(asked({"thoughts": [], "marks": [{"ref": "T1"}]}))

    with counted_queries() as statements:
        response = offer(client, alice, conversation_id)

    assert response.status_code == 200 and response.json() == {"proposal": None}
    assert "marks" not in propose_tool(fake.chat_requests[0])["function"]["parameters"]["properties"]
    assert seen["parts"] == [] and mark_check_statements(statements) == []
    assert fake.embed_requests == [] and lookups == []
    assert go_ahead(client, alice, conversation_id, action, fake) == 200


@pytest.mark.parametrize(
    "marks",
    [
        [{"ref": "T1"}],
        [{"ref": "T1", "summary": "He came on Tuesday."}],
        [{"summary": "no ref"}],
    ],
    ids=["valid", "with-summary", "no-ref"],
)
@pytest.mark.parametrize("action", ["compact", "archive"])
def test_a_mark_beside_a_new_thought_is_ignored(
    client, alice, test_database_url, fake, talk, monkeypatch, marks, action
):
    _, conversation_id, lookups = talk
    seen = spy(monkeypatch)
    fake.queue(asked({"thoughts": [OAT_MILK], "marks": marks}))

    with counted_queries() as statements:
        response = offer(client, alice, conversation_id)

    assert response.status_code == 200, response.text
    offered = response.json()["proposal"]
    assert [(p["title"], p["mark"]) for p in offered["parts"]] == [("Buy oat milk", None)]
    [parts] = seen["parts"]
    assert not any("mark" in p or "mark_ref" in p for p in parts)
    assert mark_check_statements(statements) == []
    # Only the new part is embedded and looked up.
    [request] = fake.embed_requests
    assert len(request["input"]) == 1 and lookups == ["Buy oat milk groceries"]
    # The offered proposal is held; the action goes ahead after it.
    assert go_ahead(client, alice, conversation_id, action, fake) == 200


def test_the_second_asked_call_has_no_marks_and_a_done_candidate_is_marked(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    stored = milk(test_database_url, alice_id)
    mark_done(test_database_url, stored, DONE_DAY)
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=(*EARLIER, "I need oat milk again", "Noted.")
    )
    seed_active_index(test_database_url, alice_id)
    fake_similar(monkeypatch, {"oat milk": [stored]})
    seen = spy(monkeypatch)
    fake.queue(
        asked({"thoughts": [OAT_MILK]}),
        asked(
            {
                "thoughts": [{**OAT_MILK, "new": True}],
                "marks": [{"ref": "T1", "summary": "Bought it last time."}],
            }
        ),
    )

    response = offer(client, alice, conversation_id)

    assert response.status_code == 200, response.text
    assert len(fake.chat_requests) == 2
    for request in fake.chat_requests:
        assert "marks" not in propose_tool(request)["function"]["parameters"]["properties"]
    note = system_notes(fake.chat_requests[1])[-1]
    [line] = [line for line in note.splitlines() if "Buy oat milk · filed" in line]
    assert line.startswith("T1 · Buy oat milk · filed ") and " · done 2026-11-05" in line
    offered = response.json()["proposal"]
    assert [(p["title"], p["mark"]) for p in offered["parts"]] == [("Buy oat milk", None)]
    [_, parts] = [None, *seen["parts"]]
    assert not any("mark" in p or "mark_ref" in p for p in parts)
    assert go_ahead(client, alice, conversation_id, "compact", fake) == 200


# --- 3.6: a status part does not count as filing ---


def confirmed_mark(thought_id) -> dict:
    return {**status_part(thought_id), "thought_id": thought_id, "seen_position": 4}


def filed_state(url, conversation_id):
    async def work(session):
        conversation = await session.get(Conversation, uuid.UUID(conversation_id))
        proposals = await list_proposals(session, conversation)
        messages = await list_messages(session, conversation)
        raw = await raw_text_for(session, conversation, messages, push=False)
        return discussion_start(proposals), raw, saved_ids(proposals)

    return run_db(url, work)


def test_a_confirmed_status_part_does_not_count_as_filing(
    client, alice, test_database_url, fake, alice_id
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        messages=("A podcast about maps?", "Sounds good.", "I called the plumber", "Ready."),
    )
    before = filed_state(test_database_url, conversation_id)
    seed_proposal(
        test_database_url, conversation_id, [confirmed_mark(task)], position=3, to_position=2, hold=False
    )

    start, raw, saved = filed_state(test_database_url, conversation_id)

    assert (start, raw) == before[:2] and start == 0
    assert raw.text == "A podcast about maps?\n\nI called the plumber"
    assert uuid.UUID(task) not in saved
    # The offer still asks the model: the podcast talk is not filed.
    fake.queue(completion("nothing"))
    assert offer(client, alice, conversation_id).json() == {"proposal": None}
    assert len(fake.chat_requests) == 1
    assert OFFER_NOTE.split(".")[0] in system_notes(fake.chat_requests[0])[-1]


def test_only_a_status_card_confirmed_since_still_asks(client, alice, test_database_url, fake, alice_id):
    """The scenario "Only a status card confirmed since"."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        messages=(*EARLIER, "I called the plumber", "Ready to confirm."),
    )
    seed_proposal(
        test_database_url,
        conversation_id,
        [confirmed_mark(task)],
        position=7,
        from_position=6,
        to_position=6,
        hold=False,
    )
    fake.queue(completion("nothing"))

    assert offer(client, alice, conversation_id).json() == {"proposal": None}
    assert len(fake.chat_requests) == 1
    assert go_ahead(client, alice, conversation_id, "compact", fake) == 200


@pytest.mark.parametrize("with_mark", [False, True])
def test_nothing_said_since_a_filed_card_asks_nothing(
    client, alice, test_database_url, fake, alice_id, with_mark
):
    """The scenario "Nothing said since the last saved card", with and
    without a confirmed mark beside the filed part."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=("I need oat milk", "Ready to confirm.")
    )
    parts = [part(title="Buy oat milk", thought_id=str(uuid.uuid4()))]
    if with_mark:
        parts.append(confirmed_mark(task))
    seed_proposal(test_database_url, conversation_id, parts, position=1, hold=False)

    assert offer(client, alice, conversation_id).json() == {"proposal": None}
    assert fake.chat_requests == []


def write(url, conversation_id, parts, refs=None):
    async def work(session):
        conversation = await session.get(Conversation, uuid.UUID(conversation_id))
        proposal, replaced = await write_proposal(session, conversation, parts, 9, refs=refs)
        await session.commit()
        return str(proposal.id), replaced

    return run_db(url, work)


def held_state(url, conversation_id):
    conversation, _, proposals = rows(url, conversation_id)
    return conversation.held_proposal_id, {str(p.id): p.replaced_by_id for p in proposals}


@pytest.mark.parametrize("earlier", [False, True])
def test_a_proposal_of_only_marks_is_not_held_and_replaces_nothing(
    client, alice, test_database_url, fake, alice_id, earlier
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    held = seed_proposal(test_database_url, conversation_id, [part()], position=3) if earlier else None

    _, replaced = write(test_database_url, conversation_id, [{"mark_ref": "T1"}])

    held_id, replaced_by = held_state(test_database_url, conversation_id)
    assert replaced is None
    assert (str(held_id) if held_id else None) == held
    if earlier:
        assert replaced_by[held] is None
    # The next turn's context has no held note for it.
    fake.queue(text_chunks("Hi!"))
    chat(client, alice, "hello again", conversation_id)
    notes = [n for n in system_notes(fake.chat_requests[0]) if n.startswith(HELD_HEAD)]
    assert all("Call the plumber" not in n for n in notes)
    assert bool(notes) is earlier


def test_an_unconfirmed_mark_alone_does_not_hold_a_proposal(
    client, alice, test_database_url, fake, alice_id
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=("hello", "Hi!", "I need oat milk", "Noted.")
    )
    seed_tool(test_database_url, conversation_id, 4, sources=[task])
    # A crafted held proposal whose only unsaved part is a mark; the
    # discussion after it is not filed.
    held = seed_proposal(
        test_database_url,
        conversation_id,
        [part(title="Buy oat milk", thought_id=str(uuid.uuid4())), status_part(task)],
        position=1,
    )
    [proposal] = rows(test_database_url, conversation_id)[2]
    assert unsaved_parts(proposal.parts) == [] and held_parts(proposal) is None

    fake.queue(completion("nothing"))
    assert offer(client, alice, conversation_id).json() == {"proposal": None}
    assert len(fake.chat_requests) == 1

    write(test_database_url, conversation_id, [part(title="Book the dentist")])
    _, replaced_by = held_state(test_database_url, conversation_id)
    assert replaced_by[held] is None


def test_an_unconfirmed_mark_beside_an_unsaved_part_is_held_without_the_mark(
    client, alice, test_database_url, fake, alice_id
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    held = seed_proposal(
        test_database_url, conversation_id, [part(title="Buy oat milk"), status_part(task)], position=3
    )
    [proposal] = rows(test_database_url, conversation_id)[2]
    assert held_parts(proposal) == proposal.parts
    assert [p["title"] for p in unsaved_parts(proposal.parts)] == ["Buy oat milk"]
    note = held_proposal_note(proposal.parts)
    assert "Title: Buy oat milk" in note and "Call the plumber" not in note

    written, replaced = write(test_database_url, conversation_id, [part(title="Book the dentist")])

    held_id, replaced_by = held_state(test_database_url, conversation_id)
    assert (str(held_id), str(replaced), str(replaced_by[held])) == (written, held, written)


# --- 3.7: the done marker ---


def test_the_seen_thoughts_note_marks_a_done_thought(client, alice, test_database_url, fake, alice_id):
    """The scenario "Done in the seen-thoughts note"."""
    done = milk(test_database_url, alice_id)
    task = plumber(test_database_url, alice_id)
    mark_done(test_database_url, done, DONE_DAY)
    conversation_id = seen_conversation(test_database_url, client, alice, done, task)

    note = refs_of(test_database_url, conversation_id).note(get_chat_config().filing)

    lines = note.splitlines()
    [milk_line] = [line for line in lines if " · Buy oat milk · " in line]
    [plumber_line] = [line for line in lines if " · Call the plumber · " in line]
    assert milk_line.startswith("T1 · Buy oat milk · filed ")
    assert " · done 2026-11-05" in milk_line
    assert " · done" not in plumber_line
    # The turn sends the same note.
    fake.queue(text_chunks("Hi!"))
    chat(client, alice, "hello", conversation_id)
    assert note in system_notes(fake.chat_requests[0])


def test_the_candidate_round_marks_a_done_candidate(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    """The scenario "Done in the similar-thought question"."""
    done = milk(test_database_url, alice_id)
    mark_done(test_database_url, done, DONE_DAY)
    eggs = seed_thought(test_database_url, alice_id, "Buy eggs", "A dozen eggs.", tags=("groceries",), category="task")
    conversation_id = seen_conversation(test_database_url, client, alice)
    fake_similar(monkeypatch, {"milk": [done, eggs]})
    fake.queue(propose({"thoughts": [OAT_MILK]}), text_chunks("Is it one of these?"))

    chat(client, alice, "I need oat milk", conversation_id)

    listing = tool_results(fake.chat_requests[1])[-1]
    [milk_line] = [line for line in listing.splitlines() if "· Buy oat milk ·" in line]
    [eggs_line] = [line for line in listing.splitlines() if "· Buy eggs ·" in line]
    assert " · done 2026-11-05" in milk_line
    assert " · done" not in eggs_line
    assert "mark it done instead" not in listing


@pytest.mark.parametrize("category, line", [("task", True), ("idea", False)])
def test_the_repeated_task_line_only_for_a_task_part(
    client, alice, test_database_url, fake, alice_id, monkeypatch, category, line
):
    stored = milk(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    fake_similar(monkeypatch, {"oat milk": [stored]})
    fake.queue(propose({"thoughts": [{**OAT_MILK, "category": category}]}), text_chunks("Same one?"))

    chat(client, alice, "oat milk", conversation_id)

    listing = tool_results(fake.chat_requests[1])[-1]
    assert REPEATED_TASK == "A repeated task is usually a new task, unless the user says they finished it."
    assert (REPEATED_TASK in listing) is line
    assert "A repeated task" in listing if line else "repeated task" not in listing
