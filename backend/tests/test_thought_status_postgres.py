"""The thought-status checks that need Postgres: layer 1 of the
similar-thought check as built (task 3.3), and confirms that store a new
thought or an addition beside a status part (task 3.8)."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.models import Proposal
from tests import test_thought_additions as additions
from tests.chat_helpers import (
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
from tests.test_similar_check import store
from tests.test_thought_additions import (
    ADDED,
    FILED,
    add,
    confirm,
    seed_addition,
    thought,
    undo,
)
from tests.test_thought_refs import seed_tool

pytestmark = pytest.mark.postgres

fake = additions.fake
lock = additions.lock
proposed = additions.proposed
added = additions.added


def status_part(thought_id, title, category="task") -> dict:
    return {
        "mark": thought_id,
        "title": title,
        "summary": "",
        "tags": [],
        "category": category,
        "thought_id": None,
    }


def events_of(response, name: str) -> list[dict]:
    return [data for event, data in parse_events(response.text) if event == name]


def tool_summaries(response) -> list[str]:
    return [e["summary"] for e in events_of(response, "tool") if e["phase"] == "end"]


def tool_results(request: dict) -> list[str]:
    return [m["content"] for m in request["messages"] if m["role"] == "tool"]


def proposals_of(url, conversation_id) -> list[Proposal]:
    async def work(session):
        rows = await session.execute(
            select(Proposal).where(Proposal.conversation_id == uuid.UUID(conversation_id))
        )
        return list(rows.scalars())

    return run_db(url, work)


# --- 3.3: layer 1 leaves the mark out ---


BILL = {
    "title": "Call the plumber about the bill",
    "summary": "Ask the plumber why the bill is so high.",
    "tags": ["home"],
    "category": "task",
}


@pytest.fixture
def plumber_talk(client, alice, fake, test_database_url):
    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    task = store(
        test_database_url, user_id, fake, "Call the plumber", "Call the plumber about the leak.",
        tags=["home"], category="task",
    )
    conversation_id = seed_conversation(test_database_url, client, alice)
    seed_tool(test_database_url, conversation_id, 2, sources=[task])
    fake.embed_requests.clear()
    return task, conversation_id


def test_a_mark_is_not_embedded_and_its_thought_is_no_candidate(
    client, alice, fake, test_database_url, plumber_talk
):
    task, conversation_id = plumber_talk
    fake.queue(
        tool_call_chunks("propose_thought", json.dumps({"thoughts": [BILL], "marks": [{"ref": "T1"}]})),
        text_chunks("Ready to confirm."),
    )

    response = chat(client, alice, "I called the plumber; now the bill", conversation_id)

    # Only the new part's query is embedded.
    [request] = fake.embed_requests
    assert len(request["input"]) == 1 and "bill" in request["input"][0]
    # The marked thought is no candidate: no candidate round, no similar.
    assert tool_summaries(response) == ["Proposed a thought to file"]
    [proposal] = proposals_of(test_database_url, conversation_id)
    assert [p.get("mark") for p in proposal.parts] == [None, task]
    assert "similar" not in proposal.parts[1]
    assert proposal.parts[0].get("similar") is None


def test_the_same_new_part_without_the_mark_lists_the_task(
    client, alice, fake, test_database_url, plumber_talk
):
    _, conversation_id = plumber_talk
    fake.queue(
        tool_call_chunks("propose_thought", json.dumps({"thoughts": [BILL]})),
        text_chunks("Is it the plumber task?"),
    )

    response = chat(client, alice, "now the plumber bill", conversation_id)

    assert tool_summaries(response) == ["Checked for similar thoughts"]
    assert "T1 · Call the plumber · filed " in tool_results(fake.chat_requests[1])[-1]


# --- 3.8: confirms beside a status part ---


def test_confirming_the_new_part_clears_the_held_proposal_and_the_mark_stays_confirmable(
    client, alice, lock, fake, test_database_url
):
    conversation_id = lock["conversation_id"]
    proposal_id = seed_proposal(
        test_database_url,
        conversation_id,
        [part(title="Buy oat milk"), status_part(lock["id"], lock["title"])],
        position=6,
        from_position=2,
        to_position=4,
    )

    response = confirm(client, alice, conversation_id, proposal_id, 0, **{**FILED, "title": "Buy oat milk"})

    assert response.status_code == 200, response.text
    assert response.json()["message"] == "Saved."
    assert thought(client, alice, response.json()["thought_id"])["title"] == "Buy oat milk"
    assert thought(client, alice, lock["id"])["status"] == "open"
    body = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()
    assert body["held_proposal_id"] is None

    marked = confirm(client, alice, conversation_id, proposal_id, 1)
    assert marked.json() == {"saved": True, "thought_id": lock["id"], "message": "Marked done."}
    assert thought(client, alice, lock["id"])["status"] == "done"


@pytest.mark.parametrize("mark_first", [True, False])
def test_an_addition_and_a_mark_on_one_thought_confirm_in_either_order(
    client, alice, lock, fake, test_database_url, mark_first
):
    conversation_id = lock["conversation_id"]
    proposal_id = seed_addition(
        test_database_url, conversation_id, lock, extra=[status_part(lock["id"], lock["title"])]
    )

    def mark():
        return confirm(client, alice, conversation_id, proposal_id, 1)

    def addition():
        return add(client, alice, conversation_id, proposal_id, 0)

    first, second = (mark, addition) if mark_first else (addition, mark)
    one, two = first(), second()

    assert (one.status_code, two.status_code) == (200, 200), (one.text, two.text)
    body = thought(client, alice, lock["id"])
    assert (body["status"], body["summary"]) == ("done", ADDED["summary"])


def mark_done(client, headers, url, lock, by):
    """Mark the lock task done by a confirmed status card or by the sheet."""
    if by == "mark":
        proposal_id = seed_proposal(
            url,
            lock["conversation_id"],
            [status_part(lock["id"], lock["title"])],
            position=7,
            hold=False,
        )
        response = confirm(client, headers, lock["conversation_id"], proposal_id, 0)
    else:
        response = client.patch(f"/api/thoughts/{lock['id']}", headers=headers, json={"status": "done"})
    assert response.status_code == 200, response.text
    return thought(client, headers, lock["id"])


@pytest.mark.parametrize("by", ["mark", "sheet"])
def test_marked_done_then_an_addition_confirmed(
    client, alice, lock, proposed, fake, test_database_url, by
):
    """The scenario "Marked done, then an addition confirmed"."""
    done = mark_done(client, alice, test_database_url, lock, by)

    response = add(client, alice, **proposed)

    assert response.status_code == 200, response.text
    body = thought(client, alice, lock["id"])
    assert body["summary"] == ADDED["summary"]
    assert (body["status"], body["status_changed_at"]) == ("done", done["status_changed_at"])


@pytest.mark.parametrize("by", ["mark", "sheet"])
def test_addition_marked_done_then_undone(
    client, alice, lock, added, fake, test_database_url, by
):
    """The scenario "Addition, marked done, then undone"."""
    done = mark_done(client, alice, test_database_url, lock, by)
    [addition] = added["additions"]

    response = undo(client, alice, lock["id"], addition["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["summary"], body["tags"], body["category"]) == (
        FILED["summary"],
        FILED["tags"],
        FILED["category"],
    )
    assert (body["status"], body["status_changed_at"]) == ("done", done["status_changed_at"])
