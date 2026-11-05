"""Confirming a status part, and `mark` in the payloads (thought-status tasks
3.8 and 3.9). A status-only confirm needs no search SQL, so these run on
SQLite; the checks that also confirm a new thought or an addition are in
tests/test_thought_status_postgres.py."""

import json
import uuid

import pytest
from sqlalchemy import func, select, update

from app.chat.proposal import part_lookup, proposal_payload
from app.models import Conversation, Proposal, Thought, User
from tests import test_thought_status_turn as turn_tests
from tests.chat_helpers import (
    chat,
    part,
    run_db,
    seed_proposal,
    text_chunks,
    user_id_for,
)
from tests.status_fakes import seed_active_index
from tests.test_thought_refs import delete_thought, seed_thought
from tests.test_thought_status_turn import (
    events_of,
    plumber,
    propose,
    rows,
    seen_conversation,
    status_part,
    thought_of,
)
from tests.thought_helpers import counted_queries

fake = turn_tests.fake
alice_id = turn_tests.alice_id

GONE_BODY = {"error": {"code": "not_found", "message": "This thought no longer exists."}}


def confirm(client, headers, conversation_id, proposal_id, parts=(0,), **fields):
    return client.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal_id}/confirm",
        headers=headers,
        json={"parts": list(parts), **fields},
    )


def thought_count(url, user_id) -> int:
    async def work(session):
        return (
            await session.execute(
                select(func.count()).select_from(Thought).where(Thought.user_id == uuid.UUID(user_id))
            )
        ).scalar_one()

    return run_db(url, work)


def proposal_row(url, proposal_id) -> Proposal:
    async def work(session):
        return await session.get(Proposal, uuid.UUID(proposal_id))

    return run_db(url, work)


def held_of(url, conversation_id):
    async def work(session):
        return (await session.get(Conversation, uuid.UUID(conversation_id))).held_proposal_id

    return run_db(url, work)


def rename(url, thought_id, title) -> None:
    """A title edit, as the row leaves it (the edit's search SQL needs Postgres)."""

    async def work(session):
        await session.execute(
            update(Thought).where(Thought.id == uuid.UUID(thought_id)).values(title=title)
        )
        await session.commit()

    run_db(url, work)


@pytest.fixture
def marked(client, alice, test_database_url, fake, alice_id):
    """The open task Call the plumber (T1), and a proposal that marks it done."""
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    proposal_id = seed_proposal(
        test_database_url, conversation_id, [status_part(task)], position=3, hold=False
    )
    return task, conversation_id, proposal_id


# --- 3.8: confirm ---


def test_confirming_marks_the_thought_done_and_stores_no_thought(
    client, alice, test_database_url, fake, alice_id, marked
):
    """The scenario "Status card stores no thought"."""
    task, conversation_id, proposal_id = marked
    seed_active_index(test_database_url, alice_id)
    count = thought_count(test_database_url, alice_id)

    response = confirm(client, alice, conversation_id, proposal_id)

    assert response.status_code == 200, response.text
    assert response.json() == {"saved": True, "thought_id": task, "message": "Marked done."}
    stored = thought_of(test_database_url, task)
    assert stored.status == "done" and stored.status_changed_at is not None
    assert proposal_row(test_database_url, proposal_id).parts[0]["thought_id"] == task
    assert thought_count(test_database_url, alice_id) == count
    assert fake.embed_requests == []


def test_a_second_confirm_answers_the_same_and_keeps_the_first_time(
    client, alice, test_database_url, fake, marked
):
    task, conversation_id, proposal_id = marked
    confirm(client, alice, conversation_id, proposal_id)
    first = thought_of(test_database_url, task).status_changed_at

    response = confirm(client, alice, conversation_id, proposal_id)

    assert response.json() == {"saved": True, "thought_id": task, "message": "Marked done."}
    assert thought_of(test_database_url, task).status_changed_at == first


def test_a_thought_done_in_the_sheet_is_confirmed_with_no_change(
    client, alice, test_database_url, fake, marked
):
    task, conversation_id, proposal_id = marked
    sheet = client.patch(f"/api/thoughts/{task}", headers=alice, json={"status": "done"})
    assert sheet.status_code == 200, sheet.text
    before = thought_of(test_database_url, task)

    response = confirm(client, alice, conversation_id, proposal_id)

    assert response.json()["message"] == "Marked done."
    after = thought_of(test_database_url, task)
    assert (after.status, after.status_changed_at, after.updated_at) == (
        "done",
        before.status_changed_at,
        before.updated_at,
    )


def test_a_deleted_thought_gives_404_and_nothing_changes(
    client, alice, test_database_url, fake, marked
):
    task, conversation_id, proposal_id = marked
    delete_thought(test_database_url, task)

    response = confirm(client, alice, conversation_id, proposal_id)

    assert response.status_code == 404 and response.json() == GONE_BODY
    assert proposal_row(test_database_url, proposal_id).parts[0]["thought_id"] is None


def test_another_users_thought_gives_the_same_404_and_nothing_changes(
    client, alice, bob, test_database_url, fake, alice_id
):
    bob_id = user_id_for(client, bob)
    foreign = seed_thought(test_database_url, bob_id, "Bob's secret task", category="task")
    conversation_id = seen_conversation(test_database_url, client, alice)
    # A crafted, held proposal: a new part and a mark on Bob's thought.
    proposal_id = seed_proposal(
        test_database_url, conversation_id, [part(), status_part(foreign)], position=3
    )

    response = confirm(client, alice, conversation_id, proposal_id, parts=(1,))

    assert response.status_code == 404 and response.json() == GONE_BODY
    theirs = thought_of(test_database_url, foreign)
    assert (theirs.status, theirs.status_changed_at) == ("open", None)
    assert proposal_row(test_database_url, proposal_id).parts[1]["thought_id"] is None
    assert str(held_of(test_database_url, conversation_id)) == proposal_id


def test_naming_every_part_with_a_status_part_is_refused(
    client, alice, test_database_url, fake, alice_id
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    proposal_id = seed_proposal(
        test_database_url, conversation_id, [part(), status_part(task)], position=3
    )
    count = thought_count(test_database_url, alice_id)

    response = confirm(
        client, alice, conversation_id, proposal_id, parts=(0, 1), title="Oat milk", summary="x"
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "parts: a status change is confirmed on its own"
    assert thought_count(test_database_url, alice_id) == count
    assert [p["thought_id"] for p in proposal_row(test_database_url, proposal_id).parts] == [None, None]
    assert thought_of(test_database_url, task).status == "open"


def test_the_body_fields_are_ignored(client, alice, test_database_url, fake, marked):
    task, conversation_id, proposal_id = marked

    response = confirm(
        client,
        alice,
        conversation_id,
        proposal_id,
        title="Something else",
        summary="Another summary",
        tags=["x"],
        category="no-such-category",
        when={"start": "2026-12-01"},
        mode="add",
        add_to=str(uuid.uuid4()),
        based_on="2020-01-01T00:00:00+00:00",
    )

    assert response.status_code == 200, response.text
    stored = thought_of(test_database_url, task)
    assert (stored.title, stored.summary, stored.tags, stored.category, stored.starts_on) == (
        "Call the plumber",
        "Call about the leak.",
        ["home"],
        "task",
        None,
    )


# --- 3.9: mark in the payloads ---


def test_the_stream_event_carries_mark_and_target(client, alice, test_database_url, fake, alice_id):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    fake.queue(propose({"marks": [{"ref": "T1"}]}), text_chunks("Ready to confirm."))

    [event] = events_of(chat(client, alice, "I called the plumber", conversation_id), "proposal")

    [status] = event["parts"]
    assert status["mark"] == task
    assert (status["target"]["title"], status["target"]["category"]) == ("Call the plumber", "task")
    assert (status["thought_id"], status["saved_title"], status["deleted"]) == (None, None, False)


def test_the_messages_answer_and_the_offer_carry_mark_target_and_saved_title(
    client, alice, test_database_url, fake, alice_id
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seen_conversation(test_database_url, client, alice, task)
    proposal_id = seed_proposal(
        test_database_url, conversation_id, [part(), status_part(task)], position=3
    )
    rename(test_database_url, task, "Call the plumber Bob")

    offered = client.post(f"/api/conversations/{conversation_id}/proposal", headers=alice).json()
    [_, status] = offered["proposal"]["parts"]
    assert status["mark"] == task and status["target"]["title"] == "Call the plumber Bob"

    assert confirm(client, alice, conversation_id, proposal_id, parts=(1,)).status_code == 200
    body = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()
    [_, status] = body["proposals"][0]["parts"]
    assert status["mark"] == task
    assert status["target"]["category"] == "task"
    assert (status["thought_id"], status["saved_title"]) == (task, "Call the plumber Bob")

    delete_thought(test_database_url, task)
    body = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()
    [_, status] = body["proposals"][0]["parts"]
    assert status["target"] == {"deleted": True}
    assert (status["saved_title"], status["deleted"]) == (None, True)


def test_another_users_thought_behind_a_mark_reads_as_deleted_everywhere(
    client, alice, bob, test_database_url, fake, alice_id
):
    bob_id = user_id_for(client, bob)
    foreign = seed_thought(
        test_database_url, bob_id, "Bob's secret task", "Bob's own words.", category="secret-kind"
    )
    conversation_id = seen_conversation(test_database_url, client, alice)
    crafted = {**status_part(foreign), "title": "crafted", "category": None}
    proposal_id = seed_proposal(test_database_url, conversation_id, [part(), crafted], position=3)

    def assert_hidden(payload):
        [_, status] = payload["parts"]
        assert status["mark"] == foreign and status["target"] == {"deleted": True}
        text = json.dumps(payload)
        assert "Bob's secret task" not in text and "secret-kind" not in text

    # The stream event's payload, as the turn builds it.
    async def event(session):
        proposal = await session.get(Proposal, uuid.UUID(proposal_id))
        alice_row = await session.get(Conversation, uuid.UUID(conversation_id))
        user = await session.get(User, alice_row.user_id)
        return proposal_payload(proposal, await part_lookup(session, user, [proposal]))

    assert_hidden(json.loads(json.dumps(run_db(test_database_url, event))))
    assert_hidden(client.get(f"/api/conversations/{conversation_id}", headers=alice).json()["proposals"][0])
    offered = client.post(f"/api/conversations/{conversation_id}/proposal", headers=alice).json()
    assert_hidden(offered["proposal"])


def test_the_messages_answer_reads_no_more_for_more_status_parts(
    client, alice, test_database_url, fake, alice_id
):
    tasks = [seed_thought(test_database_url, alice_id, f"Task {n}", category="task") for n in range(4)]
    one = seen_conversation(test_database_url, client, alice, *tasks)
    many = seen_conversation(test_database_url, client, alice, *tasks)
    seed_proposal(test_database_url, one, [status_part(tasks[0])], position=3, hold=False)
    seed_proposal(
        test_database_url, many, [status_part(task) for task in tasks], position=3, hold=False
    )

    def counted(conversation_id):
        with counted_queries() as statements:
            response = client.get(f"/api/conversations/{conversation_id}", headers=alice)
        assert response.status_code == 200
        return list(statements)

    assert len(counted(many)) == len(counted(one))
    assert rows(test_database_url, many)[2][0].parts[3]["mark"] == tasks[3]

