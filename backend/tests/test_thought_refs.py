"""Refs and the seen-thoughts note (thought-appending tasks 2.1 to 2.3)."""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.chat.config import FilingConfig, get_chat_config
from app.chat.prompt import (
    OFFER_NOTE,
    OFFER_SEEN_NOTE,
    build_context,
    held_proposal_note,
    propose_tool_schema,
    seen_thoughts_note,
    system_prompt,
)
from app.chat.refs import Refs, appearances, conversation_refs
from app.chat.tools import ToolArgumentError, format_search_result, parse_proposal
from app.config import get_settings
from app.models import Conversation, Message, Proposal, Thought
from app.thoughts.categories import FIXED_CATEGORIES
from app.thoughts.search import Hit, SearchResult
from tests.chat_helpers import (
    MODEL_LIST,
    FakeLLM,
    chat,
    completion,
    part,
    ready_user,
    run_db,
    seed_conversation,
    seed_proposal,
    text_chunks,
    tool_call,
    tool_call_chunks,
    user_id_for,
)
from tests.sse_helpers import parse_events
from tests.thought_helpers import EMBED_MODEL, models_with_embedding

CATEGORIES = list(FIXED_CATEGORIES)
FILING = FilingConfig(known_tags=40)
UUID_TEXT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


# --- helpers ---


def seed_thought(url, user_id, title, summary=None, tags=("misc",), category="note", days_ago=0):
    """A thought row as the store leaves it, without search entries (enough for refs)."""

    async def work(session):
        thought = Thought(
            user_id=uuid.UUID(str(user_id)),
            title=title,
            summary=summary or f"{title}: the summary.",
            tags=list(tags),
            category=category,
            created_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
        session.add(thought)
        await session.commit()
        return str(thought.id)

    return run_db(url, work)


def seed_tool(url, conversation_id, position, sources=(), similar=()):
    """A tool message with the thoughts a search returned and a check found."""

    def listed(ids):
        return [{"id": thought_id, "title": "t", "created_at": "2026-01-01", "tags": []} for thought_id in ids]

    async def work(session):
        details = {}
        if sources:
            details["sources"] = listed(sources)
        if similar:
            details["similar"] = listed(similar)
        session.add(
            Message(
                conversation_id=uuid.UUID(conversation_id),
                position=position,
                role="tool",
                tool_call_id=f"call_{position}",
                content="result",
                details=details,
            )
        )
        await session.commit()

    run_db(url, work)


def delete_thought(url, thought_id):
    async def work(session):
        await session.execute(delete(Thought).where(Thought.id == uuid.UUID(thought_id)))
        await session.commit()

    run_db(url, work)


def refs_of(url, conversation_id) -> Refs:
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
        return await conversation_refs(session, conversation.user_id, messages, proposals)

    return run_db(url, work)


def refs_by_title(refs: Refs) -> dict[str, str]:
    return {thought.title: thought.ref for thought in refs.thoughts.values()}


def stored_parts(url, conversation_id) -> list[list[dict]]:
    async def work(session):
        rows = await session.execute(
            select(Proposal)
            .where(Proposal.conversation_id == uuid.UUID(conversation_id))
            .order_by(Proposal.position, Proposal.created_at)
        )
        return [proposal.parts for proposal in rows.scalars()]

    return run_db(url, work)


def thought_row(url, thought_id) -> Thought:
    async def work(session):
        return await session.get(Thought, uuid.UUID(thought_id))

    return run_db(url, work)


def system_notes(request: dict) -> list[str]:
    return [m["content"] for m in request["messages"] if m["role"] == "system"]


def tool_results(request: dict) -> list[str]:
    return [m["content"] for m in request["messages"] if m["role"] == "tool"]


# --- 2.1: refs by first appearance ---


def message(position, role="tool", details=None):
    return Message(position=position, role=role, content="x", details=details, compacted=False)


def proposal_row(position, parts):
    return Proposal(position=position, from_position=0, to_position=0, raw_text="x", parts=parts)


def test_numbering_follows_first_appearance_across_every_kind_of_row():
    filed, added, found, candidate, later = (uuid.uuid4() for _ in range(5))
    messages = [
        message(0, "user"),
        message(3, details={"sources": [{"id": str(found)}, {"id": str(filed)}]}),
        message(5, details={"similar": [{"id": str(candidate)}]}),
        message(8, details={"sources": [{"id": str(later)}, {"id": str(found)}]}),
    ]
    proposals = [
        # Confirmed at once, before the search at 3.
        proposal_row(1, [part(thought_id=str(filed)) | {"seen_position": 2}]),
        # An addition to the candidate the check found at 5.
        proposal_row(6, [part(), part() | {"add_to": str(added)}]),
    ]

    order = list(dict.fromkeys(appearances(messages, proposals)))

    assert order == [filed, found, candidate, added, later]


def test_within_one_position_sources_come_before_candidates_and_parts():
    source, candidate, filed = (uuid.uuid4() for _ in range(3))
    messages = [message(4, details={"similar": [{"id": str(candidate)}], "sources": [{"id": str(source)}]})]
    proposals = [proposal_row(4, [part() | {"similar": {"thought_id": str(filed)}}])]

    assert appearances(messages, proposals) == [source, candidate, filed]


def test_a_part_confirmed_late_counts_where_it_was_confirmed():
    """A thought first seen in a search between the proposal and its confirm
    keeps its ref when the card is confirmed later."""
    filed, found = uuid.uuid4(), uuid.uuid4()
    messages = [message(3, details={"sources": [{"id": str(found)}]})]
    confirmed_late = [proposal_row(1, [part(thought_id=str(filed)) | {"seen_position": 4}])]
    # A part saved before seen_position existed counts at its proposal.
    older = [proposal_row(1, [part(thought_id=str(filed))])]

    assert appearances(messages, confirmed_late) == [found, filed]
    assert appearances(messages, older) == [filed, found]


def test_rows_that_name_no_thought_are_skipped():
    messages = [
        message(1, details={"sources": [{"id": "not-a-uuid"}, "text", {"title": "no id"}]}),
        message(2, details={"sources": "nothing"}),
        message(3, role="assistant", details={"sources": [{"id": str(uuid.uuid4())}]}),
    ]
    assert appearances(messages, [proposal_row(1, [part(), "junk"])]) == []


def test_refs_number_the_conversations_thoughts_and_list_them_most_recent_first(
    client, alice, test_database_url
):
    user_id = user_id_for(client, alice)
    url = test_database_url
    lock, podcast, maps = (seed_thought(url, user_id, title) for title in ("Bike lock", "Podcast", "Maps"))
    conversation_id = seed_conversation(url, client, alice, messages=("a", "b", "c", "d"))
    seed_proposal(url, conversation_id, [part(thought_id=lock)], position=1, hold=False)
    seed_tool(url, conversation_id, 4, sources=[podcast, maps])
    seed_tool(url, conversation_id, 5, sources=[lock])

    refs = refs_of(url, conversation_id)

    assert refs_by_title(refs) == {"Bike lock": "T1", "Podcast": "T2", "Maps": "T3"}
    assert [thought.title for thought in refs.seen()] == ["Bike lock", "Maps", "Podcast"]
    assert refs.resolve("T2").title == "Podcast" and refs.resolve(" t2 ").title == "Podcast"
    assert refs.resolve("T4") is None and refs.resolve("T0") is None and refs.resolve("2") is None


def test_deleting_a_thought_keeps_every_other_ref_and_never_reuses_its_number(
    client, alice, test_database_url
):
    user_id = user_id_for(client, alice)
    url = test_database_url
    lock, podcast, maps = (seed_thought(url, user_id, title) for title in ("Bike lock", "Podcast", "Maps"))
    conversation_id = seed_conversation(url, client, alice, messages=("a", "b"))
    seed_tool(url, conversation_id, 2, sources=[lock, podcast, maps])
    before = refs_by_title(refs_of(url, conversation_id))

    delete_thought(url, podcast)
    later = seed_thought(url, user_id, "Atlas")
    seed_tool(url, conversation_id, 3, sources=[later])
    refs = refs_of(url, conversation_id)

    assert before == {"Bike lock": "T1", "Podcast": "T2", "Maps": "T3"}
    assert refs_by_title(refs) == {"Bike lock": "T1", "Maps": "T3", "Atlas": "T4"}
    assert refs.resolve("T2") is None
    assert "Podcast" not in [thought.title for thought in refs.seen()]


def test_another_users_thought_in_a_crafted_row_gets_no_ref(client, alice, bob, test_database_url):
    url = test_database_url
    bobs = seed_thought(url, user_id_for(client, bob), "Bob's secret")
    alices = seed_thought(url, user_id_for(client, alice), "Bike lock")
    conversation_id = seed_conversation(url, client, alice, messages=("a", "b"))
    seed_proposal(url, conversation_id, [part(thought_id=bobs)], position=1, hold=False)
    seed_tool(url, conversation_id, 2, sources=[bobs, alices])

    refs = refs_of(url, conversation_id)

    assert refs.ref_of(uuid.UUID(bobs)) is None
    assert refs_by_title(refs) == {"Bike lock": "T1"}
    assert refs.resolve("T1").title == "Bike lock" and refs.resolve("T2") is None
    assert "Bob's secret" not in (refs.note(FILING) or "")


# --- 2.2: the seen-thoughts note ---


def seen(ref, title, summary="A summary.", tags=("misc",), category="note"):
    from app.chat.refs import SeenThought

    now = datetime(2026, 3, 1, tzinfo=UTC)
    return SeenThought(
        ref=ref,
        id=uuid.uuid4(),
        title=title,
        summary=summary,
        tags=list(tags),
        category=category,
        created_at=now,
        updated_at=now,
    )


def test_the_note_lists_ref_title_date_tags_category_and_summary_and_no_id():
    thoughts = [seen("T2", "Podcast about maps", tags=("listen", "maps"), category="idea")]

    note = seen_thoughts_note(thoughts, 3, 1500)

    assert note.startswith("Thoughts this conversation has seen, most recently seen first")
    assert "set add_to to its ref" in note
    assert "T2 · Podcast about maps · filed 2026-03-01 · #listen #maps · idea\n   A summary." in note
    assert not UUID_TEXT.search(note)


def test_the_note_is_capped_by_count_and_summary_length():
    thoughts = [seen("T3", "Newest", summary="word " * 50), seen("T1", "Middle"), seen("T2", "Oldest")]

    note = seen_thoughts_note(thoughts, 2, 20)

    assert "Newest" in note and "Middle" in note and "Oldest" not in note
    assert note.index("Newest") < note.index("Middle")
    assert "   word word word word…" in note
    assert seen_thoughts_note([], 3, 1500) is None


def test_the_shipped_settings_name_the_caps():
    filing = get_chat_config().filing
    assert (filing.seen_thoughts, filing.seen_summary_chars) == (3, 1500)


def test_the_note_comes_after_the_messages_and_before_the_held_note():
    user = Message(position=0, role="user", content="hi", compacted=False)
    held = [part(title="Lock colours") | {"add_to": "some-id"}]

    context = build_context([user], held, seen_note="SEEN", refs={"some-id": "T1"})

    assert [m["content"] for m in context] == [
        system_prompt(),
        "hi",
        "SEEN",
        held_proposal_note(held, {"some-id": "T1"}),
    ]
    assert "Adds to: T1" in context[-1]["content"]
    assert "Adds to" not in held_proposal_note(held)
    assert [m["content"] for m in build_context([user])] == [system_prompt(), "hi"]


@pytest.fixture
def turn_user(client, alice, test_database_url):
    ready_user(client, alice)
    return user_id_for(client, alice)


def test_a_turn_tells_the_model_the_seen_thoughts_most_recent_first_before_the_held_note(
    client, alice, fake_llm, test_database_url, turn_user
):
    url = test_database_url
    lock = seed_thought(url, turn_user, "Bike lock", summary="Buy a D-lock.", tags=("bike",), category="task")
    podcast = seed_thought(url, turn_user, "Podcast about maps", days_ago=365)
    gone = seed_thought(url, turn_user, "Gone")
    conversation_id = seed_conversation(url, client, alice, messages=("a", "b", "c", "d"))
    seed_proposal(url, conversation_id, [part(thought_id=lock)], position=1, hold=False)
    seed_tool(url, conversation_id, 4, sources=[gone, podcast])
    seed_proposal(url, conversation_id, [part(title="Lock colours")], position=5)
    delete_thought(url, gone)
    fake_llm.queue(text_chunks("Sure."))

    chat(client, alice, "what colours are there?", conversation_id)

    notes = system_notes(fake_llm.chat_requests[0])
    assert len(notes) == 3
    assert notes[0] == system_prompt() and notes[2].startswith("A proposal from this conversation")
    seen_note = notes[1]
    assert seen_note.startswith("Thoughts this conversation has seen")
    assert "T3 · Podcast about maps" in seen_note and "T1 · Bike lock" in seen_note
    assert seen_note.index("Podcast about maps") < seen_note.index("Bike lock")
    assert "Gone" not in seen_note and "T2" not in seen_note
    assert lock not in seen_note and podcast not in seen_note and not UUID_TEXT.search(seen_note)


def test_a_turn_with_no_seen_thoughts_has_no_note(client, alice, fake_llm, test_database_url, turn_user):
    conversation_id = seed_conversation(test_database_url, client, alice)
    # A filed thought that was deleted since is not seen any more.
    seed_proposal(test_database_url, conversation_id, [part(thought_id=str(uuid.uuid4()))], hold=False)
    fake_llm.queue(text_chunks("Hi."))

    chat(client, alice, "hello again", conversation_id)

    assert system_notes(fake_llm.chat_requests[0]) == [system_prompt()]


def test_search_results_carry_refs_in_the_tool_text(settings_env):
    config, settings = get_chat_config().search, get_settings()
    known, new = uuid.uuid4(), uuid.uuid4()
    refs = Refs([uuid.uuid4(), known], {}, [])

    def hit(thought_id, title):
        thought = Thought(
            id=thought_id,
            title=title,
            summary=f"{title}.",
            tags=["maps"],
            created_at=datetime(2025, 3, 1, tzinfo=UTC),
        )
        return Hit(thought=thought, similarity=0.8, keyword_rank=None, chunk=0)

    result = SearchResult(hits=[hit(new, "Atlas"), hit(known, "Podcast")], total=2)

    text = format_search_result(result, config, settings, refs=refs).text
    plain = format_search_result(result, config, settings).text

    assert "1. T3 · Atlas · filed 2025-03-01 · #maps" in text
    assert "2. T2 · Podcast · filed 2025-03-01 · #maps" in text
    assert refs.ref_of(new) == "T3"
    assert "1. Atlas · filed 2025-03-01 · #maps" in plain and "T3" not in plain


def offer(client, headers, conversation_id):
    return client.post(f"/api/conversations/{conversation_id}/proposal", headers=headers)


def test_the_offer_names_the_seen_thoughts_in_place_of_the_filed_titles(
    client, alice, fake_llm, test_database_url, turn_user
):
    url = test_database_url
    lock = seed_thought(url, turn_user, "Buy a bike lock", category="task")
    conversation_id = seed_conversation(
        url, client, alice, messages=("I need a bike lock", "Noted.", "red or black?", "Black.")
    )
    seed_proposal(url, conversation_id, [part(title="Buy a bike lock", thought_id=lock)], hold=False)
    fake_llm.queue(completion("nothing"))

    assert offer(client, alice, conversation_id).json() == {"proposal": None}

    notes = system_notes(fake_llm.chat_requests[0])
    assert notes[-2].startswith("Thoughts this conversation has seen")
    assert "T1 · Buy a bike lock" in notes[-2]
    assert notes[-1] == OFFER_NOTE + "\n\n" + OFFER_SEEN_NOTE
    assert not any("already filed from this conversation" in note for note in notes)


def test_the_offer_with_no_seen_thought_keeps_only_the_offer_note(
    client, alice, fake_llm, test_database_url, turn_user
):
    conversation_id = seed_conversation(test_database_url, client, alice, messages=("a dentist", "OK."))
    fake_llm.queue(completion("nothing"))

    offer(client, alice, conversation_id)

    assert system_notes(fake_llm.chat_requests[0]) == [system_prompt(), OFFER_NOTE]


# --- 2.3: add_to and new ---


def test_the_tool_schema_takes_add_to_and_new():
    properties = propose_tool_schema(CATEGORIES, [])["function"]["parameters"]["properties"]
    item = properties["thoughts"]["items"]
    assert item["properties"]["add_to"]["type"] == "string"
    assert "title here is ignored" in item["properties"]["add_to"]["description"]
    assert item["properties"]["new"]["type"] == "boolean"
    assert "add_to" not in item["required"] and "new" not in item["required"]


def thought_args(**fields):
    return {"title": "Lock colours", "summary": "Black or red.", "tags": [], "category": "task", **fields}


def test_parse_reads_add_to_and_new():
    parts = parse_proposal(
        {"thoughts": [thought_args(add_to="t2"), thought_args(new=True), thought_args(add_to="")]},
        CATEGORIES,
    )
    assert [(p.add_to, p.new) for p in parts] == [("T2", False), (None, True), (None, False)]
    assert parts[0].as_dict()["add_to_ref"] == "T2"
    assert "add_to_ref" not in parts[1].as_dict() and "new" not in parts[1].as_dict()


def test_two_parts_with_one_ref_are_refused():
    with pytest.raises(ToolArgumentError, match="two thoughts add to T1"):
        parse_proposal({"thoughts": [thought_args(add_to="T1"), thought_args(add_to=" t1")]}, CATEGORIES)
    with pytest.raises(ToolArgumentError, match="add_to must be a ref"):
        parse_proposal({"thoughts": [thought_args(add_to=1)]}, CATEGORIES)


def propose(fake_llm, *thoughts):
    fake_llm.queue(
        tool_call_chunks("propose_thought", json.dumps({"thoughts": list(thoughts)})),
        text_chunks("Ready to check."),
    )


@pytest.fixture
def lock_conversation(client, alice, test_database_url, turn_user):
    """A conversation that filed `Buy a bike lock` as T1."""
    url = test_database_url
    lock = seed_thought(url, turn_user, "Buy a bike lock", summary="A D-lock.", tags=("bike",), category="task")
    conversation_id = seed_conversation(url, client, alice, messages=("/push buy a bike lock", "Ready."))
    seed_proposal(url, conversation_id, [part(title="Buy a bike lock", thought_id=lock)], hold=False)
    return conversation_id, lock


def test_a_seen_ref_becomes_an_addition_part(client, alice, fake_llm, test_database_url, lock_conversation):
    conversation_id, lock = lock_conversation
    propose(fake_llm, thought_args(add_to="T1", title="Bike lock colours", tags=["bike", "colour"]))

    response = chat(client, alice, "black or red, under 50 euros", conversation_id)

    [[stored]] = stored_parts(test_database_url, conversation_id)[1:]
    thought = thought_row(test_database_url, lock)
    assert stored == {
        # The model's title is ignored: an addition keeps the thought's.
        "title": "Buy a bike lock",
        "summary": "Black or red.",
        "tags": ["bike", "colour"],
        "category": "task",
        "when": None,
        "when_choices": None,
        "thought_id": None,
        "add_to": lock,
        "based_on": thought.updated_at.isoformat(),
    }
    [event] = [data for name, data in parse_events(response.text) if name == "proposal"]
    assert event["parts"][0]["add_to"] == lock and event["parts"][0]["title"] == "Buy a bike lock"
    assert tool_results(fake_llm.chat_requests[1])[-1].startswith("The proposal is now shown")


def test_an_unknown_ref_becomes_a_new_part(client, alice, fake_llm, test_database_url, lock_conversation):
    conversation_id, _ = lock_conversation
    propose(fake_llm, thought_args(add_to="T7"), thought_args(add_to="the lock", title="Lock price"))

    chat(client, alice, "black or red", conversation_id)

    parts = stored_parts(test_database_url, conversation_id)[1]
    # Every stored part has the date keys (thought-dates task 2.3).
    undated = {"when": None, "when_choices": None}
    assert parts == [
        {**part(title="Lock colours", summary="Black or red.", tags=()), **undated},
        {**part(title="Lock price", summary="Black or red.", tags=()), **undated},
    ]


def test_a_deleted_ref_becomes_a_new_part(client, alice, fake_llm, test_database_url, lock_conversation):
    conversation_id, lock = lock_conversation
    delete_thought(test_database_url, lock)
    propose(fake_llm, thought_args(add_to="T1"))

    chat(client, alice, "black or red", conversation_id)

    [stored] = stored_parts(test_database_url, conversation_id)[1]
    assert stored == {
        **part(title="Lock colours", summary="Black or red.", tags=()),
        "when": None,
        "when_choices": None,
    }


def test_another_users_thought_never_becomes_a_target(
    client, alice, bob, fake_llm, test_database_url, turn_user
):
    url = test_database_url
    bobs = seed_thought(url, user_id_for(client, bob), "Bob's lock")
    conversation_id = seed_conversation(url, client, alice, messages=("a", "b"))
    # A crafted row names Bob's thought; it gets no ref, so T1 names nothing.
    seed_tool(url, conversation_id, 2, sources=[bobs])
    propose(fake_llm, thought_args(add_to="T1"))

    chat(client, alice, "black or red", conversation_id)

    [stored] = stored_parts(url, conversation_id)[0]
    assert "add_to" not in stored and stored["title"] == "Lock colours"
    assert thought_row(url, bobs).title == "Bob's lock"


def test_two_parts_with_one_ref_go_back_to_the_model_and_store_nothing(
    client, alice, fake_llm, test_database_url, lock_conversation
):
    conversation_id, _ = lock_conversation
    fake_llm.queue(
        tool_call_chunks(
            "propose_thought",
            json.dumps({"thoughts": [thought_args(add_to="T1"), thought_args(add_to="T1")]}),
        ),
        text_chunks("Let me fix that."),
    )

    chat(client, alice, "black or red", conversation_id)

    assert len(stored_parts(test_database_url, conversation_id)) == 1
    [error] = tool_results(fake_llm.chat_requests[1])
    assert error.startswith("Error: two thoughts add to T1")
    assert error.endswith("Call the tool again with valid arguments.")


def test_the_offer_resolves_a_ref_into_an_addition(
    client, alice, fake_llm, test_database_url, lock_conversation
):
    conversation_id, lock = lock_conversation
    fake_llm.queue(text_chunks("Black is the usual pick."))
    chat(client, alice, "black or red?", conversation_id)
    fake_llm.queue(
        completion(None, tool_calls=[tool_call("propose_thought", {"thoughts": [thought_args(add_to="T1")]})])
    )

    offered = offer(client, alice, conversation_id).json()["proposal"]

    assert offered["parts"][0].get("add_to") == lock, offered
    assert offered["parts"][0]["title"] == "Buy a bike lock"


def test_the_held_note_names_an_additions_ref(client, alice, fake_llm, test_database_url, lock_conversation):
    conversation_id, lock = lock_conversation
    seed_proposal(
        test_database_url,
        conversation_id,
        [part(title="Buy a bike lock") | {"add_to": lock, "based_on": "x"}],
        position=2,
    )
    fake_llm.queue(text_chunks("OK."))

    chat(client, alice, "and a light?", conversation_id)

    held_note = system_notes(fake_llm.chat_requests[0])[-1]
    assert held_note.startswith("A proposal from this conversation") and "Adds to: T1" in held_note


# --- the ref of a card confirmed late (Postgres: the store writes the thought) ---


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.mark.postgres
def test_a_card_confirmed_after_a_search_does_not_renumber_the_search(
    client, alice, fake, test_database_url
):
    ready_user(client, alice)
    url = test_database_url
    found = seed_thought(url, user_id_for(client, alice), "Podcast about maps")
    conversation_id = seed_conversation(url, client, alice, messages=("a", "b", "c"))
    proposal_id = seed_proposal(url, conversation_id, [part(title="Bike lock")], position=1)
    seed_tool(url, conversation_id, 3, sources=[found])
    assert refs_by_title(refs_of(url, conversation_id)) == {"Podcast about maps": "T1"}

    response = client.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal_id}/confirm",
        headers=alice,
        json={"parts": [0], "title": "Bike lock", "summary": "A D-lock.", "tags": [], "category": "task"},
    )

    assert response.status_code == 200, response.text
    [[stored]] = stored_parts(url, conversation_id)
    assert stored["seen_position"] == 4
    assert refs_by_title(refs_of(url, conversation_id)) == {"Podcast about maps": "T1", "Bike lock": "T2"}
    # The stamp only fixes the ref: the chat does not receive it.
    detail = client.get(f"/api/conversations/{conversation_id}", headers=alice)
    assert "Bike lock" in detail.text and "seen_position" not in detail.text
