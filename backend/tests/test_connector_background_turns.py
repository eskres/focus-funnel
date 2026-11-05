"""Connector tools in a background turn (mcp-connectors with background-turns).

A turn runs as a background task (app/chat/running.py), so its connector
sessions must end with the turn itself, not with the response that started
it: a browser that leaves does not close them early, and a turn that is
cancelled at shutdown still closes them before its claim is released.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.chat import running
from app.connector_config import get_connector_config
from app.errors import ErrorCode
from app.main import app
from app.mcp_client import get_mcp_connect
from app.models import Conversation, ConversationConnector, Message
from tests.chat_helpers import (
    Hold,
    finish_chunk,
    text_chunks,
    tool_call_chunks,
    turns_settled,
    usage_chunk,
)
from tests.connector_helpers import write_config
from tests.sse_helpers import after_first, leave, parse_events
from tests.test_connector_turns import FakeConnect


@pytest.fixture
def mcp_env(settings_env, tmp_path):
    """MCP_ENABLED with user connectors, set before the app reads its settings."""
    from app.config import get_settings

    settings_env.setenv("MCP_ENABLED", "true")
    settings_env.setenv("MCP_USER_CONNECTORS", "true")
    settings_env.setenv("MCP_CONNECTORS_PATH", str(write_config(tmp_path / "connectors.yaml", [])))
    get_settings.cache_clear()
    get_connector_config.cache_clear()
    yield
    get_settings.cache_clear()
    get_connector_config.cache_clear()


@pytest.fixture
def fake_mcp_async():
    return FakeConnect()


async def connector_on(api, fake: FakeConnect, *tools: str) -> str:
    """A conversation with the calendar connector on and `tools` switched on."""
    app.dependency_overrides[get_mcp_connect] = lambda: fake
    response = await api.http.post(
        "/api/connectors",
        headers=api.headers,
        json={"name": "calendar", "url": "http://calendar.test/mcp"},
    )
    assert response.status_code == 201, response.text
    connector_id = response.json()["id"]
    response = await api.http.post(f"/api/connectors/{connector_id}/test", headers=api.headers)
    assert response.status_code == 200, response.text
    for tool in tools:
        response = await api.http.patch(
            f"/api/connectors/{connector_id}/tools/{tool}",
            headers=api.headers,
            json={"enabled": True},
        )
        assert response.status_code == 200, response.text

    api.fake.queue(text_chunks("Hi!") + [usage_chunk()])
    response = await api.chat("hello")
    assert response.status_code == 200, response.text
    [(name, data), *_] = parse_events(response.text)
    assert name == "conversation"
    conversation_id = data["id"]

    async def link(session):
        session.add(
            ConversationConnector(
                conversation_id=uuid.UUID(conversation_id), connector_id=uuid.UUID(connector_id)
            )
        )
        await session.commit()

    await api.db(link)
    fake.reset()
    return conversation_id


def connector_round(arguments: str, call_id: str) -> list:
    return (
        tool_call_chunks("calendar__list_events", arguments, call_id)
        + [finish_chunk("tool_calls"), usage_chunk()]
    )


async def messages_of(api, conversation_id: str) -> list[Message]:
    async def work(session):
        return list(
            (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == uuid.UUID(conversation_id))
                    .order_by(Message.position)
                )
            ).scalars()
        )

    return await api.db(work)


async def claim_of(api, conversation_id: str):
    async def work(session):
        return await session.scalar(
            select(Conversation.turn_started_at).where(Conversation.id == uuid.UUID(conversation_id))
        )

    return await api.db(work)


async def test_a_connector_turn_goes_on_after_its_client_leaves_and_then_closes_the_session(
    mcp_env, fake_mcp_async, async_api
):
    api = async_api
    await api.ready()
    conversation_id = await connector_on(api, fake_mcp_async, "list_events")
    hold = Hold()
    second = connector_round('{"text": "tuesday"}', "call_2")
    # The second model call stops before its tool call until the client is gone.
    second.insert(0, hold)
    api.fake.queue(
        text_chunks("Let me look. ")[:-1] + connector_round('{"text": "monday"}', "call_1"),
        second,
        text_chunks("Two meetings.") + [usage_chunk()],
    )

    left = await leave(
        api.app,
        "/api/chat",
        api.headers,
        {"message": "what is on?", "conversation_id": conversation_id},
        after_first("delta"),
    )

    assert left.status == 200
    # The session the first call opened stays open for the rest of the turn.
    await asyncio.wait_for(hold.reached.wait(), 5)
    [session] = fake_mcp_async.sessions
    assert session.closed == 0
    hold.release.set()
    await turns_settled()

    assert running.get(uuid.UUID(conversation_id)) is None
    assert fake_mcp_async.calls == [
        ("list_events", {"text": "monday"}),
        ("list_events", {"text": "tuesday"}),
    ]
    assert len(fake_mcp_async.connects) == 1
    assert session.closed >= 1
    messages = await messages_of(api, conversation_id)
    assert [m.role for m in messages][-5:] == ["assistant", "tool", "assistant", "tool", "assistant"]
    assert (messages[-1].status, messages[-1].content) == ("complete", "Two meetings.")
    assert await claim_of(api, conversation_id) is None


async def test_a_cancelled_connector_turn_closes_the_session_and_stores_it_interrupted(
    mcp_env, fake_mcp_async, async_api
):
    api = async_api
    await api.ready()
    conversation_id = await connector_on(api, fake_mcp_async, "list_events")
    hold = Hold()
    api.fake.queue(
        connector_round('{"text": "monday"}', "call_1"),
        # The second model call is open but has sent nothing yet.
        [hold] + text_chunks("Busy."),
    )
    stay = asyncio.Event()
    watcher = asyncio.create_task(
        leave(
            api.app,
            "/api/chat",
            api.headers,
            {"message": "what is on?", "conversation_id": conversation_id},
            stay,
        )
    )
    await asyncio.wait_for(hold.reached.wait(), 5)
    [turn] = running.running_turns()
    [session] = fake_mcp_async.sessions
    assert session.closed == 0

    # What shutdown does to every running turn.
    turn.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(turn.task, 5)
    left = await asyncio.wait_for(watcher, 5)

    assert session.closed >= 1
    messages = await messages_of(api, conversation_id)
    assert [m.role for m in messages][-3:] == ["assistant", "tool", "assistant"]
    assert (messages[-1].status, messages[-1].error_code) == (
        "failed",
        ErrorCode.ANSWER_INTERRUPTED,
    )
    assert await claim_of(api, conversation_id) is None
    assert left.events[-1][0] == "error"


async def test_a_card_from_a_running_turn_is_approved_once_the_turn_has_settled(
    mcp_env, fake_mcp_async, async_api
):
    """An approval takes no claim of its own: it is refused while the turn
    that showed the card still runs in the background, and works once the
    turn has released its claim (the turn did not move on past the card)."""
    api = async_api
    await api.ready()
    conversation_id = await connector_on(api, fake_mcp_async, "create_event")
    hold = Hold()
    api.fake.queue(
        tool_call_chunks("calendar__create_event", '{"text": "dentist"}', "call_1")
        + [finish_chunk("tool_calls"), usage_chunk()],
        # The second model call is open but has sent nothing yet.
        [hold] + text_chunks("Approve it when you are ready.") + [usage_chunk()],
    )
    left = await leave(
        api.app,
        "/api/chat",
        api.headers,
        {"message": "add the dentist", "conversation_id": conversation_id},
        after_first("action"),
    )
    [action] = [data for name, data in left.events if name == "action"]
    await asyncio.wait_for(hold.reached.wait(), 5)
    path = f"/api/conversations/{conversation_id}/actions/{action['id']}"

    response = await api.http.post(path, headers=api.headers, json={"decision": "approve"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == ErrorCode.CONVERSATION_BUSY
    assert fake_mcp_async.calls == []

    hold.release.set()
    await turns_settled()
    response = await api.http.post(path, headers=api.headers, json={"decision": "approve"})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done"
    assert fake_mcp_async.calls == [("create_event", {"text": "dentist"})]
    assert await claim_of(api, conversation_id) is None
