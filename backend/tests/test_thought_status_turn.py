"""Marks through a chat turn (thought-status tasks 3.2 to 3.4).

These run on SQLite with the fakes from tests/status_fakes.py: every turn
check with a stored thought and a new part sets `fake_similar`, and every one
that needs a search hit sets `canned_search`.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import select, update

from app.chat import turn as turn_module
from app.chat.config import get_chat_config, load_chat_config
from app.chat.prompt import (
    HELD_PROPOSAL_NOTE,
    build_context,
    drop_held_note,
    held_note_of,
    held_proposal_note,
)
from app.chat.proposal import resolve_marks, write_proposal
from app.chat.refs import Refs
from app.chat.similar import SEND_MARKS_AGAIN
from app.chat.tools import (
    PROPOSAL_SHOWN,
    PROPOSAL_SHOWN_STATUS,
    ToolRefusal,
)
from app.models import Conversation, Message, Proposal, Thought
from tests.chat_helpers import (
    MODEL_LIST,
    FakeLLM,
    _SseStream,
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
from tests.sse_helpers import parse_events
from tests.status_fakes import canned_search, fake_similar, seed_active_index
from tests.test_thought_refs import delete_thought, seed_thought, seed_tool
from tests.thought_helpers import EMBED_MODEL, counted_queries, models_with_embedding

HELD_HEAD = HELD_PROPOSAL_NOTE.split("\n", 1)[0]
CLOSING = "Nothing was proposed. Call propose_thought again with the call's other parts, without "
OAT_MILK = {"title": "Buy oat milk", "summary": "Oat milk from the shop.", "tags": ["groceries"], "category": "task"}


def unseen_line(ref):
    return (
        f"Error: {ref} is not a thought this conversation has seen. Search for it with status "
        "open, then call propose_thought with the ref the search gives."
    )


def gone_line(ref):
    return f"Error: {ref} no longer exists. Do not propose marking it done; tell the user it was deleted."


def done_line(ref):
    return (
        f"Error: {ref} is already done. Do not propose marking it done; tell the user it is "
        "already done."
    )


# --- helpers ---


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def alice_id(client, alice, fake):
    ready_user(client, alice)
    return user_id_for(client, alice)


def mark_done(url, thought_id, when=datetime(2026, 11, 5, 9, 0, tzinfo=UTC)):
    async def work(session):
        await session.execute(
            update(Thought)
            .where(Thought.id == uuid.UUID(thought_id))
            .values(status="done", status_changed_at=when)
        )
        await session.commit()

    run_db(url, work)


def thought_of(url, thought_id) -> Thought:
    async def work(session):
        return await session.get(Thought, uuid.UUID(thought_id))

    return run_db(url, work)


def plumber(url, user_id, **fields) -> str:
    return seed_thought(
        url, user_id, "Call the plumber", "Call about the leak.", tags=("home",), category="task", **fields
    )


def milk(url, user_id, **fields) -> str:
    return seed_thought(
        url, user_id, "Buy oat milk", "Oat milk from the shop.", tags=("groceries",), category="task", **fields
    )


def seen_conversation(url, client, headers, *thought_ids) -> str:
    """A conversation whose search at position 2 found these thoughts: T1, T2, …"""
    conversation_id = seed_conversation(url, client, headers, messages=("hello", "Hi!"))
    if thought_ids:
        seed_tool(url, conversation_id, 2, sources=list(thought_ids))
    return conversation_id


def propose(arguments: dict, call_id: str = "call_1") -> list:
    return tool_call_chunks("propose_thought", json.dumps(arguments), call_id=call_id)


def search(arguments: dict, call_id: str = "call_s") -> list:
    return tool_call_chunks("search_thoughts", json.dumps(arguments), call_id=call_id)


def events_of(response, name: str) -> list[dict]:
    return [data for event, data in parse_events(response.text) if event == name]


def tool_ends(response) -> list[dict]:
    return [event for event in events_of(response, "tool") if event["phase"] == "end"]


def tool_summaries(response) -> list[str]:
    return [event["summary"] for event in tool_ends(response)]


def tool_results(request: dict) -> list[str]:
    return [m["content"] for m in request["messages"] if m["role"] == "tool"]


def system_notes(request: dict) -> list[str]:
    return [m["content"] for m in request["messages"] if m["role"] == "system"]


def has_held_note(request: dict) -> bool:
    return any(note.startswith(HELD_HEAD) for note in system_notes(request))


def rows(url, conversation_id):
    async def work(session):
        conversation = await session.get(Conversation, uuid.UUID(conversation_id))
        messages = list(
            (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.position)
                )
            ).scalars()
        )
        proposals = list(
            (
                await session.execute(
                    select(Proposal)
                    .where(Proposal.conversation_id == conversation.id)
                    .order_by(Proposal.position, Proposal.created_at)
                )
            ).scalars()
        )
        return conversation, messages, proposals

    return run_db(url, work)


def proposals_of(url, conversation_id) -> list[Proposal]:
    return rows(url, conversation_id)[2]


def ended_complete(response, url, conversation_id) -> bool:
    _, messages, _ = rows(url, conversation_id)
    last = messages[-1]
    return (
        bool(events_of(response, "done"))
        and not events_of(response, "error")
        and (last.role, last.status, last.error_code) == ("assistant", "complete", None)
    )


def status_part(thought_id, title="Call the plumber", category="task") -> dict:
    return {
        "mark": thought_id,
        "title": title,
        "summary": "",
        "tags": [],
        "category": category,
        "thought_id": None,
    }


# --- 3.2: resolving marks ---


def test_a_seen_ref_stores_the_thought_as_a_mark(client, alice, test_database_url, fake, alice_id):
    """Also the scenario "Only a mark, with no new thoughts"."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    fake.queue(propose({"marks": [{"ref": "T1"}]}), text_chunks("Ready to confirm."))

    response = chat(client, alice, "I called the plumber", conversation_id)

    [event] = events_of(response, "proposal")
    assert [p["mark"] for p in event["parts"]] == [task]
    assert event["parts"][0]["target"]["title"] == "Call the plumber"
    [proposal] = proposals_of(test_database_url, conversation_id)
    assert proposal.parts == [status_part(task)]
    assert ended_complete(response, test_database_url, conversation_id)


@pytest.mark.parametrize("case", ["unseen", "deleted", "done"])
def test_a_mark_that_cannot_apply_is_refused_and_the_turn_goes_on(
    client, alice, test_database_url, fake, alice_id, monkeypatch, case
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    if case == "deleted":
        delete_thought(test_database_url, task)
    if case == "done":
        mark_done(test_database_url, task)
    ref = "T9" if case == "unseen" else "T1"
    expected = {"unseen": unseen_line, "deleted": gone_line, "done": done_line}[case](ref)
    fake_similar(monkeypatch, {})
    fake.queue(
        propose({"marks": [{"ref": ref}]}),
        propose({"thoughts": [OAT_MILK]}, call_id="call_2"),
        text_chunks("Ready."),
    )

    response = chat(client, alice, "I called the plumber", conversation_id)

    assert tool_results(fake.chat_requests[1])[-1] == expected
    assert tool_summaries(response) == ["Could not propose that change", "Proposed a thought to file"]
    # The refused call stored nothing; the corrected one is shown.
    [proposal] = proposals_of(test_database_url, conversation_id)
    assert [p["title"] for p in proposal.parts] == ["Buy oat milk"]
    assert len(events_of(response, "proposal")) == 1
    assert ended_complete(response, test_database_url, conversation_id)


def bob_done_thought(client, bob, url) -> str:
    bob_id = user_id_for(client, bob)
    thought_id = seed_thought(url, bob_id, "Bob's secret task", category="task")
    mark_done(url, thought_id)
    return thought_id


def test_another_users_done_thought_reads_as_gone_with_the_owner_in_the_query(
    client, alice, bob, test_database_url, fake, alice_id
):
    foreign = bob_done_thought(client, bob, test_database_url)
    conversation_id = seen_conversation(test_database_url, client, alice)
    numbered = [uuid.uuid4() for _ in range(8)] + [uuid.UUID(foreign)]

    async def work(session):
        conversation = await session.get(Conversation, uuid.UUID(conversation_id))
        with counted_queries() as statements, pytest.raises(ToolRefusal) as refusal:
            await write_proposal(
                session,
                conversation,
                [{"mark_ref": "T9"}],
                5,
                refs=Refs(numbered, {}, []),
            )
        return str(refusal.value), list(statements)

    text, statements = run_db(test_database_url, work)

    assert text == gone_line("T9")
    [check] = [s for s in statements if "thoughts.status" in s and "thoughts.user_id" in s]
    assert "FROM thoughts" in check
    assert proposals_of(test_database_url, conversation_id) == []


def test_another_users_thought_behind_a_crafted_ref_never_reads_as_done(
    client, alice, bob, test_database_url, fake, alice_id
):
    foreign = bob_done_thought(client, bob, test_database_url)
    conversation_id = seen_conversation(test_database_url, client, alice, foreign)
    fake.queue(propose({"marks": [{"ref": "T1"}]}), text_chunks("Sorry."))

    response = chat(client, alice, "I did Bob's task", conversation_id)

    result = tool_results(fake.chat_requests[1])[-1]
    assert result.startswith("Error: T1")
    assert not any("already done" in line for line in result.splitlines())
    assert "Bob's secret task" not in json.dumps(fake.chat_requests[1])
    assert proposals_of(test_database_url, conversation_id) == []
    assert tool_summaries(response) == ["Could not propose that change"]


def test_two_bad_marks_get_one_result_in_the_order_of_the_call(
    client, alice, test_database_url, fake, alice_id
):
    gone = plumber(test_database_url, alice_id)
    done = milk(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, gone, done)
    delete_thought(test_database_url, gone)
    mark_done(test_database_url, done)
    fake.queue(propose({"marks": [{"ref": "T1"}, {"ref": "T2"}]}), text_chunks("Both are settled."))

    response = chat(client, alice, "I called the plumber and bought the milk", conversation_id)

    # Only refused marks: no closing line.
    assert tool_results(fake.chat_requests[1])[-1] == "\n".join([gone_line("T1"), done_line("T2")])
    assert proposals_of(test_database_url, conversation_id) == []
    assert tool_summaries(response) == ["Could not propose that change"]


def resolve(url, user_id, numbered, marks, others):
    async def work(session):
        try:
            return await resolve_marks(
                session, uuid.UUID(user_id), Refs(numbered, {}, []), marks, others
            )
        except ToolRefusal as refusal:
            return str(refusal)

    return run_db(url, work)


def test_the_closing_line_names_every_refused_ref(test_database_url, client, alice, alice_id, fake):
    open_task = plumber(test_database_url, alice_id)
    done = milk(test_database_url, alice_id)
    mark_done(test_database_url, done)
    numbered = [uuid.UUID(open_task)] + [uuid.uuid4() for _ in range(7)]
    numbered += [uuid.UUID(done), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]  # T9 done, T12 gone

    def run(marks, others):
        return resolve(test_database_url, alice_id, numbered, marks, others)

    # Only refused marks: no closing line.
    assert run(["T9"], 0) == done_line("T9")
    # With an entry in thoughts, or a mark that passed.
    assert run(["T9"], 1) == done_line("T9") + "\n" + CLOSING + "T9."
    assert run(["T1", "T9"], 0) == done_line("T9") + "\n" + CLOSING + "T9."
    assert run(["T9", "T12"], 1) == "\n".join(
        [done_line("T9"), gone_line("T12"), CLOSING + "T9 and T12."]
    )
    # An unseen ref beside a new part asks for the search's ref too.
    assert run(["T20"], 1) == (
        unseen_line("T20") + "\n" + CLOSING + "T20, and with the ref the search gives, in one call."
    )
    assert run(["plumber", "T9"], 1).endswith(
        "without plumber and T9, and with the ref the search gives, in one call."
    )
    for text in (run(["T9"], 1), run(["T12"], 1), run(["T20"], 1)):
        assert "Do not propose it;" not in text
    # A mark that passes is stored with nothing from the model.
    assert run(["T1"], 0) == [
        {"mark": open_task, "title": "", "summary": "", "tags": [], "category": None, "thought_id": None}
    ]


def test_refused_mark_beside_a_new_thought(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    """The scenario "Refused mark beside a new thought"."""
    task = plumber(test_database_url, alice_id)
    mark_done(test_database_url, task)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    seed_active_index(test_database_url, alice_id)
    fake_similar(monkeypatch, {})
    fake.queue(
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T1"}]}),
        propose({"thoughts": [OAT_MILK]}, call_id="call_2"),
        text_chunks("The plumber task is already done; the oat milk is ready to confirm."),
    )

    response = chat(client, alice, "I called the plumber, and I need to buy oat milk", conversation_id)

    assert tool_results(fake.chat_requests[1])[-1] == done_line("T1") + "\n" + CLOSING + "T1."
    # The refused call made no embedding call; the next one checks its part.
    assert len(fake.embed_requests) == 1
    [event] = events_of(response, "proposal")
    assert [p["title"] for p in event["parts"]] == ["Buy oat milk"]
    [proposal] = proposals_of(test_database_url, conversation_id)
    assert [p.get("mark") for p in proposal.parts] == [None]
    assert ended_complete(response, test_database_url, conversation_id)


def test_a_refused_mark_beside_a_new_part_makes_no_embedding_call(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    seed_active_index(test_database_url, alice_id)
    lookups = fake_similar(monkeypatch, {})
    fake.queue(propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T7"}]}), text_chunks("Let me look."))

    chat(client, alice, "I called the plumber, and I need to buy oat milk", conversation_id)

    assert fake.embed_requests == [] and lookups == []
    assert proposals_of(test_database_url, conversation_id) == []


def test_a_parse_error_keeps_the_suffix_and_its_summary(client, alice, test_database_url, fake, alice_id):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    fake.queue(
        propose({"marks": [{"ref": "T1", "summary": "He came on Tuesday."}]}),
        text_chunks("Let me try again later."),
    )

    response = chat(client, alice, "I called the plumber, he came Tuesday", conversation_id)

    assert tool_results(fake.chat_requests[1])[-1] == (
        "Error: marks[0]: a mark only names a ref; send an addition as its own entry in "
        "thoughts. Call the tool again with valid arguments."
    )
    assert tool_summaries(response) == ["The tool call was not valid"]


def test_the_same_ref_twice_stores_one_status_part(client, alice, test_database_url, fake, alice_id):
    ids = [seed_thought(test_database_url, alice_id, f"Task {n}", category="task") for n in (1, 2, 3)]
    conversation_id = seen_conversation(test_database_url, client, alice, *ids)
    fake.queue(propose({"marks": [{"ref": "T3"}, {"ref": "T3"}]}), text_chunks("Ready."))

    response = chat(client, alice, "I did task 3", conversation_id)

    [proposal] = proposals_of(test_database_url, conversation_id)
    assert proposal.parts == [status_part(ids[2], title="Task 3")]
    assert tool_summaries(response) == ["Proposed marking a thought done"]


def test_an_addition_and_a_mark_on_one_thought_are_both_stored(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    fake_similar(monkeypatch, {})
    addition = {
        "title": "Call the plumber",
        "summary": "Called him; he fixed the leak on Tuesday.",
        "tags": ["home"],
        "category": "task",
        "add_to": "T1",
    }
    fake.queue(propose({"thoughts": [addition], "marks": [{"ref": "T1"}]}), text_chunks("Ready."))

    chat(client, alice, "I called the plumber, he fixed the leak", conversation_id)

    [proposal] = proposals_of(test_database_url, conversation_id)
    assert [(p.get("add_to"), p.get("mark")) for p in proposal.parts] == [(task, None), (None, task)]


def test_a_new_thought_and_a_mark_are_both_stored_the_mark_last(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    fake_similar(monkeypatch, {})
    fake.queue(
        # The marks come first in the call; they are stored last.
        propose({"marks": [{"ref": "T1"}], "thoughts": [OAT_MILK]}),
        text_chunks("Ready to confirm."),
    )

    response = chat(client, alice, "I called the plumber, and I need oat milk", conversation_id)

    [proposal] = proposals_of(test_database_url, conversation_id)
    assert proposal.parts[0]["title"] == "Buy oat milk" and "mark" not in proposal.parts[0]
    assert proposal.parts[1] == status_part(task)
    assert tool_summaries(response) == ["Proposed a thought to file"]


# --- 3.2: the held note ---


def held_milk(url, conversation_id) -> str:
    return seed_proposal(url, conversation_id, [part(title="Buy oat milk")], position=2)


def test_a_refused_call_keeps_the_held_note_and_the_held_proposal(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    held = held_milk(test_database_url, conversation_id)
    fake_similar(monkeypatch, {})
    fake.queue(
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T4"}]}),
        text_chunks("Let me look for the plumber task."),
    )

    chat(client, alice, "I called the plumber", conversation_id)

    assert has_held_note(fake.chat_requests[0])
    assert tool_results(fake.chat_requests[1])[-1].startswith(unseen_line("T4"))
    assert has_held_note(fake.chat_requests[1])
    conversation, _, proposals = rows(test_database_url, conversation_id)
    assert str(conversation.held_proposal_id) == held
    assert [(str(p.id), p.replaced_by_id) for p in proposals] == [(held, None)]


def test_a_candidate_round_keeps_the_held_note_and_the_held_parts(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    stored = milk(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    held = held_milk(test_database_url, conversation_id)
    fake_similar(monkeypatch, {"oat milk": [stored]})
    tools: list = []
    original = turn_module.BuiltinTools.__init__

    def keep(self, *args, **kwargs):
        original(self, *args, **kwargs)
        tools.append(self)

    monkeypatch.setattr(turn_module.BuiltinTools, "__init__", keep)
    seen: dict = {}

    def second_round(request: httpx2.Request) -> httpx2.Response:
        seen["held_parts"] = tools[0].held_parts
        seen["held_note"] = tools[0].held_note
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_SseStream(text_chunks("Is this the oat milk you filed?")),
        )

    fake.queue(propose({"thoughts": [OAT_MILK]}), second_round)

    response = chat(client, alice, "and the oat milk again", conversation_id)

    assert tool_summaries(response) == ["Checked for similar thoughts"]
    assert has_held_note(fake.chat_requests[1])
    assert seen["held_parts"] is not None and seen["held_note"] is not None
    conversation, _, proposals = rows(test_database_url, conversation_id)
    assert str(conversation.held_proposal_id) == held
    assert len(proposals) == 1


def test_a_written_proposal_drops_the_held_note(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    held_milk(test_database_url, conversation_id)
    fake_similar(monkeypatch, {})
    fake.queue(
        propose({"thoughts": [OAT_MILK, {**OAT_MILK, "title": "Book the dentist"}]}),
        text_chunks("Ready."),
    )

    chat(client, alice, "and I need to book the dentist", conversation_id)

    assert has_held_note(fake.chat_requests[0])
    assert not has_held_note(fake.chat_requests[1])


def test_a_written_proposal_drops_the_held_note_after_its_rows_changed(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    """The held part's date changes in the rows during the turn (here inside
    the search), so a second render of the note would differ from the one
    the context holds: the note is still dropped after the proposal."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    dated = {**part(title="Buy oat milk"), "when": {"start": "2026-11-10", "end": None, "time_zone": "UTC"}}
    held = seed_proposal(test_database_url, conversation_id, [dated], position=2)
    fake_similar(monkeypatch, {})
    canned_search(monkeypatch, task)
    search_tool_result = turn_module.search_tool_result

    async def search_and_move_the_date(session, user, arguments, **options):
        moved = {**dated, "when": {"start": "2026-11-17", "end": None, "time_zone": "UTC"}}
        await session.execute(
            update(Proposal).where(Proposal.id == uuid.UUID(held)).values(parts=[moved])
        )
        await session.commit()
        return await search_tool_result(session, user, arguments, **options)

    monkeypatch.setattr(turn_module, "search_tool_result", search_and_move_the_date)
    fake.queue(
        search({"query": "plumber", "status": "open"}),
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T1"}]}, call_id="call_2"),
        text_chunks("Ready to confirm."),
    )

    chat(client, alice, "I called the plumber", conversation_id)

    [sent] = [n for n in system_notes(fake.chat_requests[1]) if n.startswith(HELD_HEAD)]
    _, _, proposals = rows(test_database_url, conversation_id)
    [row] = [p for p in proposals if str(p.id) == held]
    assert held_proposal_note(row.parts) != sent
    assert len(fake.chat_requests) == 3
    assert not has_held_note(fake.chat_requests[2])


def test_the_held_note_is_dropped_by_identity_even_when_a_render_differs():
    held = [
        {**part(title="Buy oat milk"), "when": {"start": "2026-11-10", "end": None, "time_zone": "UTC"}},
        {**part(title="Add to the plumber task"), "add_to": "abc"},
    ]
    context = build_context([], held, refs={"abc": "T1"})
    note = held_note_of(context, held)
    assert note is context[-1] and note["content"].startswith(HELD_HEAD)
    # The rows change: the date moves and the ref is gone.
    held[0]["when"] = {"start": "2026-11-17", "end": None, "time_zone": "UTC"}
    assert held_proposal_note(held, {}) != note["content"]

    drop_held_note(context, note)

    assert not any((m.get("content") or "").startswith(HELD_HEAD) for m in context)
    assert held_note_of(build_context([], None), None) is None


# --- 3.3: marks and the similar-thought check ---


def test_a_call_with_only_a_mark_makes_no_embedding_call_and_no_candidate_round(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    """The scenario "Only a mark"."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    seed_active_index(test_database_url, alice_id)
    lookups = fake_similar(monkeypatch, {"plumber": [task]})
    fake.queue(propose({"marks": [{"ref": "T1"}]}), text_chunks("Ready to confirm."))

    response = chat(client, alice, "I called the plumber", conversation_id)

    assert fake.embed_requests == [] and lookups == []
    assert tool_summaries(response) == ["Proposed marking a thought done"]
    assert len(events_of(response, "proposal")) == 1


def test_a_candidate_round_for_a_call_with_marks_asks_for_them_again(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    task = plumber(test_database_url, alice_id)
    stored = milk(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    seed_active_index(test_database_url, alice_id)
    fake_similar(monkeypatch, {"oat milk": [stored]})
    fake.queue(
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T1"}]}),
        text_chunks("Is it the same oat milk?"),
    )

    response = chat(client, alice, "I called the plumber, and I need oat milk", conversation_id)

    [listing] = tool_results(fake.chat_requests[1])[-1:]
    assert tool_summaries(response) == ["Checked for similar thoughts"]
    assert listing.rstrip().endswith(SEND_MARKS_AGAIN)
    # Only the new part was embedded and looked up.
    [request] = fake.embed_requests
    assert len(request["input"]) == 1 and "oat milk" in request["input"][0].lower()


def test_a_candidate_round_without_marks_has_no_marks_line(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    stored = milk(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    fake_similar(monkeypatch, {"oat milk": [stored]})
    fake.queue(propose({"thoughts": [OAT_MILK]}), text_chunks("Is it the same oat milk?"))

    chat(client, alice, "I need oat milk", conversation_id)

    [listing] = tool_results(fake.chat_requests[1])[-1:]
    assert listing.startswith("Nothing was proposed yet") and SEND_MARKS_AGAIN not in listing


def test_the_mark_survives_a_candidate_round(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    """The scenario "Mark kept through a similar-thought question"."""
    ids = [seed_thought(test_database_url, alice_id, f"Task {n}", category="task") for n in (1, 2)]
    task = plumber(test_database_url, alice_id)
    stored = milk(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, *ids, task)
    fake_similar(monkeypatch, {"oat milk": [stored]})
    fake.queue(
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T3"}]}),
        propose({"thoughts": [{**OAT_MILK, "new": True}], "marks": [{"ref": "T3"}]}, call_id="call_2"),
        text_chunks("Ready to confirm."),
    )

    response = chat(client, alice, "I called the plumber, and I need oat milk", conversation_id)

    assert tool_summaries(response) == ["Checked for similar thoughts", "Proposed a thought to file"]
    [event] = events_of(response, "proposal")
    assert [p["mark"] for p in event["parts"]] == [None, task]
    # The marked thought is never a candidate of the other parts.
    assert "Call the plumber" not in tool_results(fake.chat_requests[1])[-1]


def test_a_refused_call_does_not_count_for_the_layer_2_skip(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    task = plumber(test_database_url, alice_id)
    stored = milk(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    seed_active_index(test_database_url, alice_id)
    fake_similar(monkeypatch, {"oat milk": [stored]})
    fake.queue(
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T9"}]}),
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T1"}]}, call_id="call_2"),
        text_chunks("Is it the same oat milk?"),
    )

    response = chat(client, alice, "I called the plumber, and I need oat milk", conversation_id)

    assert tool_summaries(response) == ["Could not propose that change", "Checked for similar thoughts"]
    # The refused call made no embedding call; the second one ran layer 1.
    assert len(fake.embed_requests) == 1
    assert proposals_of(test_database_url, conversation_id) == []


def test_the_guessed_ref_flow_with_a_candidate_round_takes_five_calls(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    """Design decision 11's one flow that can need five calls: the fourth
    call's proposal is shown, and the turn ends with tool_loop_limit."""
    task = plumber(test_database_url, alice_id)
    stored = milk(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    canned_search(monkeypatch, task)
    fake_similar(monkeypatch, {"oat milk": [stored]})
    fake.queue(
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T9"}]}),
        search({"query": "plumber", "status": "open"}),
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T1"}]}, call_id="call_3"),
        propose({"thoughts": [{**OAT_MILK, "new": True}], "marks": [{"ref": "T1"}]}, call_id="call_4"),
        text_chunks("Never asked for."),
    )

    response = chat(client, alice, "I called the plumber, and I need oat milk", conversation_id)

    assert get_chat_config().tool_rounds == 4
    assert len(fake.chat_requests) == 4
    assert tool_summaries(response) == [
        "Could not propose that change",
        "Searched your thoughts for “plumber”",
        "Checked for similar thoughts",
        "Proposed a thought to file",
    ]
    [event] = events_of(response, "proposal")
    assert [(p["title"], p["mark"]) for p in event["parts"]] == [
        ("Buy oat milk", None),
        ("Call the plumber", task),
    ]
    [error] = events_of(response, "error")
    assert error["error"]["code"] == "tool_loop_limit"
    assert events_of(response, "delta") == []
    fake.replies.clear()


# --- 3.4: the tool result, the summary, and four rounds ---


def test_proposal_shown_status_says_nothing_changes_until_confirmed():
    assert "Nothing changes until they confirm" in PROPOSAL_SHOWN_STATUS
    for word in ("marked done", "closed", "finished"):
        assert word in PROPOSAL_SHOWN_STATUS
    assert "marked done" not in PROPOSAL_SHOWN


@pytest.mark.parametrize(
    "arguments, result, summary",
    [
        ({"marks": [{"ref": "T1"}]}, PROPOSAL_SHOWN_STATUS, "Proposed marking a thought done"),
        (
            {"thoughts": [OAT_MILK], "marks": [{"ref": "T1"}]},
            PROPOSAL_SHOWN_STATUS,
            "Proposed a thought to file",
        ),
        ({"thoughts": [OAT_MILK]}, PROPOSAL_SHOWN, "Proposed a thought to file"),
    ],
)
def test_the_tool_result_and_summary_follow_the_parts(
    client, alice, test_database_url, fake, alice_id, monkeypatch, arguments, result, summary
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    fake_similar(monkeypatch, {})
    fake.queue(propose(arguments), text_chunks("Ready to confirm."))

    response = chat(client, alice, "I called the plumber", conversation_id)

    assert tool_results(fake.chat_requests[1])[-1] == result
    assert tool_summaries(response) == [summary]
    _, messages, [proposal] = rows(test_database_url, conversation_id)
    [tool] = [m for m in messages if m.role == "tool" and m.position > 2]
    assert tool.details == {"proposal_id": str(proposal.id), "summary": summary}


def test_every_tool_message_stores_its_summary(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    canned_search(monkeypatch, task)
    fake.queue(
        propose({"marks": [{"ref": "T5"}]}),
        propose({"marks": [{"ref": "T5", "new": True}]}, call_id="call_2"),
        search({"status": "open", "category": "task"}, call_id="call_3"),
        propose({"marks": [{"ref": "T1"}]}, call_id="call_4"),
    )

    response = chat(client, alice, "I called the plumber", conversation_id)

    _, messages, [proposal] = rows(test_database_url, conversation_id)
    stored = [m.details for m in messages if m.role == "tool" and m.position > 2]
    assert [details["summary"] for details in stored] == tool_summaries(response) == [
        "Could not propose that change",
        "The tool call was not valid",
        "Listed your open thoughts in task",
        "Proposed marking a thought done",
    ]
    assert [item["id"] for item in stored[2]["sources"]] == [task]
    assert stored[3]["proposal_id"] == str(proposal.id)
    fake.replies.clear()


def test_the_held_note_has_the_finished_task_sentences():
    assert (
        "If the latest message says the user finished something, make one propose_thought "
        "call that holds the held proposal and the mark" in " ".join(HELD_PROPOSAL_NOTE.split())
    )
    assert "If the user says they finished something a held part is about" in " ".join(
        HELD_PROPOSAL_NOTE.split()
    )
    assert "that is not among the thoughts this conversation has seen, first search" not in (
        " ".join(HELD_PROPOSAL_NOTE.split())
    )


def test_the_shipped_chat_yaml_has_four_tool_rounds():
    shipped = Path(__file__).parent.parent / "app" / "chat" / "chat.yaml"
    assert load_chat_config(shipped).tool_rounds == 4


@pytest.mark.parametrize("message", ["I called the plumber", "/push I called the plumber"])
def test_guessed_ref_then_search_then_mark(
    client, alice, test_database_url, fake, alice_id, monkeypatch, message
):
    """The scenario "Guessed ref, then search", also with /push."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    calls = canned_search(monkeypatch, task)
    fake.queue(
        propose({"marks": [{"ref": "T3"}]}),
        search({"query": "plumber", "status": "open"}, call_id="call_2"),
        propose({"marks": [{"ref": "T1"}]}, call_id="call_3"),
        text_chunks("Ready to confirm."),
    )

    response = chat(client, alice, message, conversation_id)

    if message.startswith("/push"):
        assert fake.chat_requests[0]["tool_choice"]["function"]["name"] == "propose_thought"
    assert calls[0]["arguments"].status == "open"
    [event] = events_of(response, "proposal")
    assert [p["mark"] for p in event["parts"]] == [task]
    assert ended_complete(response, test_database_url, conversation_id)
    assert len(fake.chat_requests) == 4


def test_push_a_finished_task_the_conversation_has_not_seen(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    """The scenario "Push a finished task the conversation has not seen"."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    fake_similar(monkeypatch, {"plumber": [task]})
    note = {"title": "Called the plumber", "summary": "Called the plumber.", "tags": ["home"], "category": "note"}
    fake.queue(
        propose({"thoughts": [note]}),
        propose({"thoughts": [], "marks": [{"ref": "T1"}]}, call_id="call_2"),
        text_chunks("Ready to confirm."),
    )

    response = chat(client, alice, "/push I called the plumber", conversation_id)

    assert "T1 · Call the plumber · filed " in tool_results(fake.chat_requests[1])[-1]
    [event] = events_of(response, "proposal")
    assert [(p["title"], p["mark"]) for p in event["parts"]] == [("Call the plumber", task)]
    assert len(fake.chat_requests) <= 3
    assert ended_complete(response, test_database_url, conversation_id)


def test_unseen_finished_task_and_something_new(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    """The scenario "Unseen finished task and something new"."""
    task = plumber(test_database_url, alice_id)
    stored = milk(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    canned_search(monkeypatch, task)
    fake_similar(monkeypatch, {"oat milk": [stored]})
    fake.queue(
        search({"query": "plumber", "status": "open"}),
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T1"}]}, call_id="call_2"),
        propose({"thoughts": [{**OAT_MILK, "new": True}], "marks": [{"ref": "T1"}]}, call_id="call_3"),
        text_chunks("Ready to confirm."),
    )

    response = chat(client, alice, "I called the plumber, and I need to buy oat milk", conversation_id)

    [event] = events_of(response, "proposal")
    assert [(p["title"], p["mark"]) for p in event["parts"]] == [
        ("Buy oat milk", None),
        ("Call the plumber", task),
    ]
    assert len(fake.chat_requests) <= 4
    assert ended_complete(response, test_database_url, conversation_id)


def test_held_proposal_and_an_unseen_finished_task(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    """The scenario "Held proposal and an unseen finished task"."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    held = held_milk(test_database_url, conversation_id)
    canned_search(monkeypatch, task)
    fake_similar(monkeypatch, {})
    fake.queue(
        search({"query": "plumber", "status": "open"}),
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T1"}]}, call_id="call_2"),
        text_chunks("Ready to confirm."),
    )

    response = chat(client, alice, "I called the plumber", conversation_id)

    [event] = events_of(response, "proposal")
    assert [p["mark"] for p in event["parts"]] == [None, task]
    assert event["replaces"] == held
    conversation, _, proposals = rows(test_database_url, conversation_id)
    assert str(conversation.held_proposal_id) == event["id"]
    assert str(proposals[0].replaced_by_id) == event["id"]
    assert len(fake.chat_requests) <= 4
    assert ended_complete(response, test_database_url, conversation_id)


def test_held_proposal_and_a_seen_finished_task(
    client, alice, test_database_url, fake, alice_id, monkeypatch
):
    """The scenario "Held proposal and a seen finished task"."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice)
    # The conversation filed the task (T1), then proposed oat milk, held.
    seed_proposal(
        test_database_url,
        conversation_id,
        [{**part(title="Call the plumber"), "thought_id": task, "seen_position": 2}],
        position=1,
        hold=False,
    )
    held = held_milk(test_database_url, conversation_id)
    fake_similar(monkeypatch, {})
    fake.queue(
        propose({"thoughts": [OAT_MILK], "marks": [{"ref": "T1"}]}),
        text_chunks("Ready to confirm."),
    )

    response = chat(client, alice, "I called the plumber", conversation_id)

    [event] = events_of(response, "proposal")
    assert [p["mark"] for p in event["parts"]] == [None, task]
    conversation, _, proposals = rows(test_database_url, conversation_id)
    assert str(conversation.held_proposal_id) == event["id"]
    assert [str(p.replaced_by_id) for p in proposals if str(p.id) == held] == [event["id"]]
    assert len(fake.chat_requests) == 2
    assert ended_complete(response, test_database_url, conversation_id)


def test_a_model_that_always_calls_a_tool_ends_after_four_calls(
    client, alice, test_database_url, fake, alice_id
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    fake.queue(
        propose({"marks": [{"ref": "T1"}]}),
        *(propose({"marks": [{"ref": "T1"}]}, call_id=f"call_{n}") for n in (2, 3, 4)),
    )

    response = chat(client, alice, "I called the plumber", conversation_id)

    assert len(fake.chat_requests) == 4
    [error] = events_of(response, "error")
    assert error["error"]["code"] == "tool_loop_limit"
    assert len(proposals_of(test_database_url, conversation_id)) == 1

