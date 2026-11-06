"""Connector actions and the moved expiry (stop-and-spend-cap task 2.5).

The MCP client is `FakeConnect` from test_connector_turns, which counts
connects and calls. A send refused before its first model call (the cap, a
full context) leaves the cards approvable; a send that reaches the model
expires them, also when the provider refuses that first call.
"""

import uuid

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.db import create_engine
from app.models import ToolAction
from tests import test_connector_actions as connector_actions
from tests import test_connector_turns as turns
from tests.chat_helpers import (
    _SseStream,
    api_error,
    chat,
    error_code,
    run_db,
    text_chunks,
    tool_call_chunks,
    user_id_for,
)
from tests.sse_helpers import parse_events
from tests.test_connector_actions import CREATE, decide
from tests.test_spend_cap import add_usage

# The connector fixtures: the app with MCP on, the fake MCP client, and a
# conversation with the calendar connector on and create_event switched on.
config_path = turns.config_path
fake_mcp = turns.fake_mcp
client = turns.client
on = turns.on
acting = connector_actions.acting


def statuses(url: str) -> dict[str, str]:
    async def work(session):
        rows = await session.execute(select(ToolAction.id, ToolAction.status))
        return {str(action_id): status for action_id, status in rows}

    return run_db(url, work)


def held_actions(client, headers, conversation_id, fake_llm, *texts: str) -> list[dict]:
    """One turn whose model calls create_event once per text; returns the action events."""
    chunks = []
    for index, text in enumerate(texts):
        chunks += tool_call_chunks(CREATE, f'{{"text": "{text}"}}', f"call_{index}", index)
    fake_llm.queue(chunks, text_chunks("They are waiting for your approval."))
    response = chat(client, headers, "add " + " and ".join(texts), conversation_id)
    events = parse_events(response.text)
    assert events[-1][0] == "done", events
    return [data for name, data in events if name == "action"]


def at_cap(client, headers, url):
    response = client.put(
        "/api/usage/cap", headers=headers, json={"cap": {"unit": "usd", "amount": 5}}
    )
    assert response.status_code == 200, response.text
    add_usage(url, user_id_for(client, headers), ("chat", 100, 10, "5.12"))


def test_a_send_refused_at_the_cap_leaves_the_actions_approvable(
    client, alice, acting, fake_llm, fake_mcp, test_database_url
):
    conversation_id = acting["conversation"]
    dentist, gym = held_actions(client, alice, conversation_id, fake_llm, "dentist", "gym")
    at_cap(client, alice, test_database_url)
    requests_before = len(fake_llm.chat_requests)

    refused = chat(client, alice, "and lunch with Sam", conversation_id)

    assert refused.status_code == 409
    assert error_code(refused) == "spend_cap_reached"
    assert len(fake_llm.chat_requests) == requests_before
    assert statuses(test_database_url) == {dentist["id"]: "pending", gym["id"]: "pending"}

    approved = decide(client, alice, conversation_id, dentist["id"])

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "done"
    assert fake_mcp.calls == [("create_event", {"text": "dentist"})]

    declined = decide(client, alice, conversation_id, gym["id"], "decline")

    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "declined"
    assert fake_mcp.calls == [("create_event", {"text": "dentist"})]
    assert statuses(test_database_url) == {dentist["id"]: "done", gym["id"]: "declined"}


def test_an_answered_send_expires_the_action_before_its_first_chunk(
    client, alice, acting, fake_llm, fake_mcp, test_database_url
):
    conversation_id = acting["conversation"]
    [action] = held_actions(client, alice, conversation_id, fake_llm, "dentist")
    seen: list[str] = []

    async def first_call(request: httpx2.Request) -> httpx2.Response:
        # Another session, while the turn's first call waits for its first chunk.
        engine = create_engine(test_database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine)() as session:
                seen.append(
                    (
                        await session.execute(
                            select(ToolAction.status).where(
                                ToolAction.id == uuid.UUID(action["id"])
                            )
                        )
                    ).scalar_one()
                )
        finally:
            await engine.dispose()
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_SseStream(text_chunks("Sure.")),
        )

    fake_llm.queue(first_call)
    response = chat(client, alice, "never mind", conversation_id)

    assert parse_events(response.text)[-1][0] == "done"
    assert seen == ["expired"]
    later = decide(client, alice, conversation_id, action["id"])
    assert later.status_code == 409
    assert error_code(later) == "action_expired"
    assert fake_mcp.calls == []


def test_a_send_refused_by_check_room_leaves_the_action_approvable(
    client, alice, acting, fake_llm, fake_mcp, test_database_url
):
    conversation_id = acting["conversation"]
    [action] = held_actions(client, alice, conversation_id, fake_llm, "dentist")
    requests_before = len(fake_llm.chat_requests)

    # Far past the model's 131,072 tokens.
    refused = chat(client, alice, "word " * 200_000, conversation_id)

    assert refused.status_code == 409
    assert error_code(refused) == "context_full"
    assert len(fake_llm.chat_requests) == requests_before
    assert statuses(test_database_url) == {action["id"]: "pending"}

    approved = decide(client, alice, conversation_id, action["id"])

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "done"
    assert fake_mcp.calls == [("create_event", {"text": "dentist"})]


def test_a_send_whose_first_call_the_provider_refuses_expires_the_action(
    client, alice, acting, fake_llm, fake_mcp, test_database_url
):
    conversation_id = acting["conversation"]
    [action] = held_actions(client, alice, conversation_id, fake_llm, "dentist")
    fake_llm.queue(api_error(401, "invalid key"))

    refused = chat(client, alice, "never mind", conversation_id)

    assert refused.status_code == 409
    assert error_code(refused) == "provider_key_rejected"
    assert statuses(test_database_url) == {action["id"]: "expired"}
    later = decide(client, alice, conversation_id, action["id"])
    assert later.status_code == 409
    assert error_code(later) == "action_expired"
    assert fake_mcp.calls == []
