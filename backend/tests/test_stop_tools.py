"""Stop and tool calls (stop-and-spend-cap task 3.2, the SQLite part;
tests/test_stop_postgres.py has the rounds that embed and confirm).

A built-in call and an acts call that writes a card always run to their
end, commit, and send their events before the turn stops. A connector call
that may reach its server is cut, and the model is told it may have run.
Every tool call gets a result, so the next request is valid.
"""

import asyncio
import json
import logging
import uuid

import pytest
from sqlalchemy import select

from app.chat import running
from app.chat import turn as turn_module
from app.errors import ErrorCode
from app import mcp_client
from app.main import app
from app.mcp_client import get_mcp_connect
from app.models import ConversationConnector, Proposal, ToolAction
from tests.chat_helpers import (
    Hold,
    finish_chunk,
    text_chunks,
    tool_call_chunks,
    turns_settled,
    usage_chunk,
)
from tests.sse_helpers import parse_events
from tests.stop_helpers import STOPPED, adding, stopped_messages, the_turn
from tests.test_background_turns import claim_of, messages_of, tool_round, watch_chat
from tests import test_connector_background_turns as connector_turns
from tests.test_connector_background_turns import connector_on
from tests.test_connector_turns import FakeConnect

PROPOSAL = {"title": "Oat milk", "summary": "Buy oat milk tomorrow.", "tags": ["shopping"]}
# MCP_ENABLED with user connectors.
mcp_env = connector_turns.mcp_env
NOT_RUN = "Not run: the user stopped the answer before this tool finished."


def two_calls(first: tuple[str, str, str], second: tuple[str, str, str], text: str = "") -> list:
    """One round that calls two tools: (name, arguments, call id) each."""
    head = text_chunks(text)[:-1] if text else []
    return (
        head
        + tool_call_chunks(*first, index=0)
        + tool_call_chunks(*second, index=1)
        + [finish_chunk("tool_calls"), usage_chunk()]
    )


def assert_every_call_answered(context: list[dict]) -> None:
    """Each assistant tool call is followed by a tool message for its id."""
    for index, message in enumerate(context):
        for call in message.get("tool_calls") or []:
            answers = [
                m for m in context[index + 1 :] if m.get("tool_call_id") == call["id"]
            ]
            assert len(answers) == 1, call


async def proposals_of(api, conversation_id: str) -> list[Proposal]:
    async def work(session):
        return list(
            (
                await session.execute(
                    select(Proposal).where(Proposal.conversation_id == uuid.UUID(conversation_id))
                )
            ).scalars()
        )

    return await api.db(work)


async def actions_of(api, conversation_id: str) -> list[ToolAction]:
    async def work(session):
        return list(
            (
                await session.execute(
                    select(ToolAction).where(
                        ToolAction.conversation_id == uuid.UUID(conversation_id)
                    )
                )
            ).scalars()
        )

    return await api.db(work)


def names(left) -> list[str]:
    return [name for name, _ in left.events]


async def next_turn_context(api, conversation_id: str) -> list[dict]:
    """Send one more message and return the context its model call got."""
    api.fake.queue(text_chunks("Sure.") + [usage_chunk()])
    response = await api.chat("and now?", conversation_id)
    assert parse_events(response.text)[-1] == ("done", {}), response.text
    return api.fake.chat_requests[-1]["messages"]


# --- built-in tools run to their end ---


async def test_a_stop_during_a_search_lets_it_finish_and_skips_the_proposal_after_it(
    async_api, cancel_spy, monkeypatch
):
    api = async_api
    await api.ready()
    entered, gate = asyncio.Event(), asyncio.Event()
    real_search = turn_module.search_tool_result

    async def slow_search(*args, **kwargs):
        entered.set()
        await asyncio.wait_for(gate.wait(), 5)
        return await real_search(*args, **kwargs)

    monkeypatch.setattr(turn_module, "search_tool_result", slow_search)
    api.fake.queue(
        two_calls(
            ("search_thoughts", '{"query": "milk"}', "call_s"),
            ("propose_thought", json.dumps(PROPOSAL), "call_p"),
            text="Let me look. ",
        )
    )
    watcher = await watch_chat(api, "I need oat milk")
    await asyncio.wait_for(entered.wait(), 5)
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    await asyncio.sleep(0.05)
    assert cancel_spy(turn) == 0
    gate.set()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 0
    assert left.events[-1] == STOPPED
    ends = [data for name, data in left.events if name == "tool" and data["phase"] == "end"]
    assert [end["name"] for end in ends] == ["search_thoughts"]
    assert "proposal" not in names(left)
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.tool_call_id, m.status) for m in messages] == [
        ("user", None, "complete"),
        ("assistant", None, "complete"),
        ("tool", "call_s", "complete"),
        ("tool", "call_p", "complete"),
        ("assistant", None, "stopped"),
    ]
    assert "sources" in messages[2].details
    assert (messages[3].content, messages[3].details) == (NOT_RUN, {"stopped": True})
    assert (messages[4].content, messages[4].details) == (None, None)
    assert await proposals_of(api, conversation_id) == []
    assert len(api.fake.chat_requests) == 1

    context = await next_turn_context(api, conversation_id)
    assert_every_call_answered(context)
    assert {"role": "tool", "tool_call_id": "call_p", "content": NOT_RUN} in context


async def test_a_stop_while_the_model_sends_a_calls_arguments_stores_no_call(
    async_api, cancel_spy
):
    api = async_api
    await api.ready()
    round_one = text_chunks("Let me look. ")[:-1] + tool_call_chunks(
        "search_thoughts", '{"query": "oat milk"}', "call_s"
    )
    hold = Hold()
    # After the call's name and half its arguments.
    round_one.insert(len(round_one) - 1, hold)
    api.fake.queue(round_one + [finish_chunk("tool_calls"), usage_chunk()])
    watcher = await watch_chat(api, "what milk?")
    await asyncio.wait_for(hold.reached.wait(), 5)
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 1
    assert names(left) == ["conversation", "delta", "tool", "error"]
    assert left.events[2] == ("tool", {"name": "search_thoughts", "phase": "start"})
    assert left.events[-1] == STOPPED
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content, m.tool_calls) for m in messages] == [
        ("user", "complete", "what milk?", None),
        ("assistant", "stopped", "Let me look. ", None),
    ]
    assert messages[1].details == {"stopped_tools": ["search_thoughts"]}

    context = await next_turn_context(api, conversation_id)
    assert not any(m.get("tool_calls") for m in context)
    assert not any(m["role"] == "tool" for m in context)


async def test_a_stop_in_the_second_round_keeps_the_first_rounds_search(async_api, cancel_spy):
    api = async_api
    await api.ready()
    hold = Hold()
    api.fake.queue(
        tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Let me look. "),
        text_chunks("Found ")[:-1] + [hold] + text_chunks("nothing."),
    )
    watcher = await watch_chat(api, "what milk?")
    await asyncio.wait_for(hold.reached.wait(), 5)
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 1
    assert left.events[-1] == STOPPED
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content) for m in messages] == [
        ("user", "complete", "what milk?"),
        ("assistant", "complete", "Let me look. "),
        ("tool", "complete", messages[2].content),
        ("assistant", "stopped", "Found "),
    ]
    assert "sources" in messages[2].details
    assert api.fake.streams[1].closed


async def test_a_stop_while_the_proposal_is_committed_still_sends_its_card(
    async_api, cancel_spy, block_commit
):
    api = async_api
    await api.ready()
    blocked = block_commit(adding(role="tool", tool_call_id="call_p"))
    api.fake.queue(
        two_calls(
            ("propose_thought", json.dumps(PROPOSAL), "call_p"),
            ("search_thoughts", '{"query": "milk"}', "call_s"),
        )
    )
    watcher = await watch_chat(api, "I need oat milk")
    await blocked.reached()
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    await asyncio.sleep(0.05)
    assert cancel_spy(turn) == 0
    blocked.release.set()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 0
    tail = [
        (name, data.get("phase") if name == "tool" else None) for name, data in left.events[-3:]
    ]
    assert tail == [("proposal", None), ("tool", "end"), ("error", None)]
    assert left.events[-1] == STOPPED
    [proposal] = await proposals_of(api, conversation_id)
    [card] = [data for name, data in left.events if name == "proposal"]
    assert card["id"] == str(proposal.id)
    messages = await messages_of(api, conversation_id)
    by_call = {m.tool_call_id: m for m in messages if m.role == "tool"}
    assert by_call["call_p"].details["proposal_id"] == str(proposal.id)
    assert (by_call["call_s"].content, by_call["call_s"].details) == (NOT_RUN, {"stopped": True})
    assert api.fake.embed_requests == []
    assert len(await stopped_messages(api, conversation_id)) == 1


# --- connector calls: a card is kept, a running call may have run ---


async def test_a_stop_while_an_action_card_is_committed_still_sends_it(
    mcp_env, async_api, cancel_spy, block_commit
):
    api = async_api
    await api.ready()
    fake = FakeConnect()
    conversation_id = await connector_on(api, fake, "create_event")
    blocked = block_commit(adding(role="tool", tool_call_id="call_a"))
    api.fake.queue(
        tool_call_chunks("calendar__create_event", '{"text": "dentist"}', "call_a")
        + [finish_chunk("tool_calls"), usage_chunk()],
        text_chunks("Never asked."),
    )
    watcher = await watch_chat(api, "add the dentist", conversation_id)
    await blocked.reached()
    turn = the_turn()

    turn.stop()
    assert cancel_spy(turn) == 0
    blocked.release.set()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 0
    assert names(left)[-3:] == ["action", "tool", "error"]
    assert left.events[-1] == STOPPED
    [action] = await actions_of(api, conversation_id)
    assert action.status == "pending"
    assert fake.calls == []
    assert len(api.fake.chat_requests) == 2  # connector_on's hello, then this round


async def test_a_card_shown_before_a_stop_can_be_approved_after_it(
    mcp_env, async_api, cancel_spy
):
    api = async_api
    await api.ready()
    fake = FakeConnect()
    conversation_id = await connector_on(api, fake, "create_event")
    hold = Hold()
    api.fake.queue(
        tool_call_chunks("calendar__create_event", '{"text": "dentist"}', "call_a")
        + [finish_chunk("tool_calls"), usage_chunk()],
        [hold] + text_chunks("Approve it when you are ready."),
    )
    watcher = await watch_chat(api, "add the dentist", conversation_id)
    await asyncio.wait_for(hold.reached.wait(), 5)
    turn = the_turn()

    turn.stop()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert left.events[-1] == STOPPED
    [action] = await actions_of(api, conversation_id)
    assert action.status == "pending"
    messages = await messages_of(api, conversation_id)
    assert [m.role for m in messages][-3:] == ["assistant", "tool", "assistant"]
    assert messages[-2].details["action_id"] == str(action.id)
    assert messages[-1].status == "stopped"

    response = await api.http.post(
        f"/api/conversations/{conversation_id}/actions/{action.id}",
        headers=api.headers,
        json={"decision": "approve"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done"
    assert fake.calls == [("create_event", {"text": "dentist"})]


async def test_a_stop_in_the_first_round_keeps_older_cards_expired(
    mcp_env, async_api, cancel_spy
):
    api = async_api
    await api.ready()
    fake = FakeConnect()
    conversation_id = await connector_on(api, fake, "create_event")
    api.fake.queue(
        tool_call_chunks("calendar__create_event", '{"text": "dentist"}', "call_a")
        + [finish_chunk("tool_calls"), usage_chunk()],
        text_chunks("Approve it when you are ready.") + [usage_chunk()],
    )
    response = await api.chat("add the dentist", conversation_id)
    assert parse_events(response.text)[-1] == ("done", {})
    [action] = await actions_of(api, conversation_id)
    assert action.status == "pending"

    hold = Hold()
    # Stopped after the first delta, before the round's usage is recorded.
    api.fake.queue(text_chunks("Something ")[:-1] + [hold] + text_chunks("else."))
    watcher = await watch_chat(api, "never mind, something else", conversation_id)
    await asyncio.wait_for(hold.reached.wait(), 5)
    turn = the_turn()
    turn.stop()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert left.events[-1] == STOPPED
    [action] = await actions_of(api, conversation_id)
    assert action.status == "expired"
    response = await api.http.post(
        f"/api/conversations/{conversation_id}/actions/{action.id}",
        headers=api.headers,
        json={"decision": "approve"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == ErrorCode.ACTION_EXPIRED
    assert fake.calls == []


@pytest.fixture
async def real_mcp(mcp_server):
    mcp_server.reset()
    yield mcp_server
    mcp_server.reset()


async def real_connector_on(api, server, tool: str) -> str:
    """A conversation with a connector on the MCP test server, through the
    real SDK client, whose `tool` is switched on and always allowed."""
    app.dependency_overrides.pop(get_mcp_connect, None)
    response = await api.http.post(
        "/api/connectors", headers=api.headers, json={"name": "calendar", "url": server.url}
    )
    assert response.status_code == 201, response.text
    connector_id = response.json()["id"]
    response = await api.http.post(f"/api/connectors/{connector_id}/test", headers=api.headers)
    assert response.status_code == 200, response.text
    response = await api.http.patch(
        f"/api/connectors/{connector_id}/tools/{tool}",
        headers=api.headers,
        json={"enabled": True, "always_allow": True},
    )
    assert response.status_code == 200, response.text
    api.fake.queue(text_chunks("Hi!") + [usage_chunk()])
    response = await api.chat("hello")
    conversation_id = parse_events(response.text)[0][1]["id"]

    async def link(session):
        session.add(
            ConversationConnector(
                conversation_id=uuid.UUID(conversation_id), connector_id=uuid.UUID(connector_id)
            )
        )
        await session.commit()

    await api.db(link)
    return conversation_id


async def test_a_stop_during_a_connector_call_says_it_may_have_run(
    mcp_env, async_api, cancel_spy, real_mcp, caplog
):
    import threading

    api = async_api
    await api.ready()
    conversation_id = await real_connector_on(api, real_mcp, "create_event")
    opened = []

    async def recording(*args, **kwargs):
        session = await mcp_client.connect(*args, **kwargs)
        opened.append(session)
        return session

    app.dependency_overrides[get_mcp_connect] = lambda: recording
    real_mcp.hold_create = threading.Event()
    api.fake.queue(
        two_calls(
            ("calendar__create_event", '{"text": "dentist"}', "call_a"),
            ("calendar__create_event", '{"text": "plumber"}', "call_b"),
        )
    )

    with caplog.at_level(logging.DEBUG):
        watcher = await watch_chat(api, "add the dentist and the plumber", conversation_id)
        assert await asyncio.to_thread(real_mcp.create_entered.wait, 5)
        turn = the_turn()
        assert turn.control.interruptible

        turn.stop()
        left = await asyncio.wait_for(watcher, 10)
        await turns_settled(10)
        real_mcp.hold_create.set()

    assert cancel_spy(turn) == 1
    assert left.events[-1] == STOPPED
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.tool_call_id) for m in messages][-4:] == [
        ("assistant", None),
        ("tool", "call_a"),
        ("tool", "call_b"),
        ("assistant", None),
    ]
    may_have_run = (
        "Stopped while calendar__create_event was running. It may have run; "
        "check before running it again."
    )
    assert (messages[-3].content, messages[-3].details) == (may_have_run, {"stopped": True})
    assert (messages[-2].content, messages[-2].details) == (NOT_RUN, {"stopped": True})
    assert (messages[-1].status, messages[-1].content) == ("stopped", None)
    # The connector's session ended in the turn: its client task is done
    # and the server holds no connection from it. (This SDK gives no
    # session id, so no DELETE ends the session.)
    [session] = opened
    assert session._task is None
    assert real_mcp.open_connections() == 0
    assert await claim_of(api, conversation_id) is None
    assert running.running_turns() == []
    for problem in ("MissingGreenlet", "different task", "Could not"):
        assert problem not in caplog.text

    real_mcp.hold_create = None
    context = await next_turn_context(api, conversation_id)
    assert {"role": "tool", "tool_call_id": "call_a", "content": may_have_run} in context
    assert {"role": "tool", "tool_call_id": "call_a", "content": NOT_RUN} not in context
    assert_every_call_answered(context)
