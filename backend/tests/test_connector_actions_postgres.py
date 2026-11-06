"""Approvals on Postgres (openspec mcp-connectors task 7.3): two concurrent
approvals run the tool once, and a turn expires what is still waiting."""

import asyncio
import threading
import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from app.models import ToolAction
from tests.chat_helpers import chat, run_db, text_chunks
from tests.sse_helpers import parse_events

from tests import test_connector_actions as actions_tests
from tests import test_connector_turns as turns

pytestmark = pytest.mark.postgres

config_path = turns.config_path
fake_mcp = turns.fake_mcp
client = turns.client
on = turns.on
acting = actions_tests.acting


def test_two_concurrent_approvals_run_the_tool_once_on_postgres(
    client, alice, acting, fake_llm, fake_mcp, test_database_url, monkeypatch
):
    action = actions_tests.held_action(client, alice, acting["conversation"], fake_llm)
    actions_tests.run_twice_at_once(
        test_database_url, client, alice, acting["conversation"], action["id"], fake_mcp,
        monkeypatch,
    )


def test_approving_after_the_next_turn_started_is_expired_on_postgres(
    client, alice, acting, fake_llm, fake_mcp, test_database_url
):
    actions_tests.test_approving_after_the_next_turn_started_gives_action_expired(
        client, alice, acting, fake_llm, fake_mcp, test_database_url
    )


def test_an_approval_that_checked_before_a_message_claimed_cannot_run_on_postgres(
    client, alice, acting, fake_llm, fake_mcp, test_database_url, monkeypatch
):
    actions_tests.test_an_approval_that_checked_before_a_message_claimed_cannot_run_during_its_turn(
        client, alice, acting, fake_llm, fake_mcp, test_database_url, monkeypatch
    )


def test_the_turn_waits_for_an_approval_whose_move_began_before_the_claim(
    client, alice, acting, fake_llm, fake_mcp, test_database_url
):
    """stop-and-spend-cap design decision 30: an approval's move that began
    before the claim's commit and commits after it. The turn's wait locks
    the open rows, so it sees the card running and gets its outcome."""
    action = actions_tests.held_action(client, alice, acting["conversation"], fake_llm)
    moving = threading.Event()

    def move_slowly():
        async def work(session):
            # The approval's conditional update, held open for a moment.
            await session.execute(
                update(ToolAction)
                .where(ToolAction.id == uuid.UUID(action["id"]))
                .values(status="running", updated_at=datetime.now(UTC))
            )
            moving.set()
            await asyncio.sleep(1.0)
            await session.commit()

        run_db(test_database_url, work)
        # The approval's call returns a moment later.
        time.sleep(0.5)
        actions_tests.set_action(test_database_url, status="done", result="Created.")

    approval = threading.Thread(target=move_slowly)
    approval.start()
    try:
        assert moving.wait(10)
        fake_llm.queue(text_chunks("Sure."))
        response = chat(client, alice, "did it get added?", acting["conversation"])
    finally:
        approval.join()

    assert [name for name, _ in parse_events(response.text)][-1] == "done"
    assert actions_tests.actions(test_database_url)[0].status == "done"
    notes = [m["content"] for m in fake_llm.chat_requests[-1]["messages"] if m["role"] == "system"]
    assert any(
        note.startswith(f"The user approved {actions_tests.CREATE}. It ran and returned:")
        for note in notes
    )
