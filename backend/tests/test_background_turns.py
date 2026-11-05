"""A turn runs to its end when its browser goes away (background-turns 1.2-1.4)."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.chat import running
from app.demo_keys import held_keys
from app.errors import ErrorCode
from app.models import Conversation, Message, Proposal, UsageEvent
from tests.chat_helpers import (
    NANO,
    Hold,
    MidStreamFailure,
    finish_chunk,
    text_chunks,
    tool_call_chunks,
    turns_settled,
    usage_chunk,
)
from tests.sse_helpers import after_first, leave, parse_events

PROPOSAL = {"title": "Oat milk", "summary": "Buy oat milk tomorrow.", "tags": ["shopping"]}


async def leave_chat(api, message: str, when, conversation_id: str | None = None, **extra):
    body = {"message": message, **extra}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return await leave(api.app, "/api/chat", api.headers, body, when)


def conversation_id_from(left) -> str:
    return next(data["id"] for name, data in left.events if name == "conversation")


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
        return (
            await session.execute(
                select(Conversation.turn_started_at).where(
                    Conversation.id == uuid.UUID(conversation_id)
                )
            )
        ).scalar_one()

    return await api.db(work)


async def usage_rows(api) -> list[UsageEvent]:
    async def work(session):
        return list((await session.execute(select(UsageEvent))).scalars())

    return await api.db(work)


def tool_round(name: str, arguments: str, call_id: str, text: str = "") -> list:
    head = text_chunks(text)[:-1] if text else []
    return head + tool_call_chunks(name, arguments, call_id) + [finish_chunk("tool_calls"), usage_chunk()]


# --- 1.2 the turn goes on without its browser ---


async def test_a_turn_finishes_and_is_stored_after_its_client_disconnects(async_api):
    api = async_api
    await api.ready()
    hold = Hold()
    first = tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Let me look. ")
    # The stream stops after the first piece of text until the client is gone.
    first.insert(2, hold)
    api.fake.queue(
        first,
        tool_round("propose_thought", json.dumps(PROPOSAL), "call_p"),
        text_chunks("Filed it for you.") + [usage_chunk()],
    )

    left = await leave_chat(api, "I need oat milk", after_first("delta"))

    assert left.status == 200
    assert left.names == ["conversation", "delta"]
    conversation_id = conversation_id_from(left)
    assert running.get(uuid.UUID(conversation_id)) is not None
    hold.release.set()
    await turns_settled()

    assert running.get(uuid.UUID(conversation_id)) is None
    messages = await messages_of(api, conversation_id)
    assert [m.role for m in messages] == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert {m.status for m in messages if m.role == "assistant"} == {"complete"}
    assert messages[1].content == "Let me look. "
    assert messages[1].tool_calls[0]["function"]["name"] == "search_thoughts"
    assert "sources" in messages[2].details
    assert messages[3].tool_calls[0]["function"]["name"] == "propose_thought"
    [proposal_id] = await api.db(lambda s: _proposal_ids(s, conversation_id))
    assert messages[4].details == {"proposal_id": str(proposal_id)}
    assert messages[5].content == "Filed it for you."
    rows = await usage_rows(api)
    assert len(rows) == len(api.fake.chat_requests) == 3
    assert {(row.kind, row.model) for row in rows} == {("chat", NANO)}
    assert await claim_of(api, conversation_id) is None

    api.fake.queue(text_chunks("Next one.") + [usage_chunk()])
    response = await api.chat("and bread", conversation_id)

    assert response.status_code == 200
    assert [name for name, _ in parse_events(response.text)] == ["delta", "usage", "done"]


async def _proposal_ids(session, conversation_id):
    return list(
        (
            await session.execute(
                select(Proposal.id).where(Proposal.conversation_id == uuid.UUID(conversation_id))
            )
        ).scalars()
    )


async def test_the_post_stream_ends_only_once_the_conversation_is_free(async_api):
    api = async_api
    await api.ready()
    api.fake.queue(text_chunks("Hi!") + [usage_chunk()])

    response = await api.chat("hello")

    events = parse_events(response.text)
    assert [name for name, _ in events] == ["conversation", "delta", "usage", "done"]
    conversation_id = events[0][1]["id"]
    assert await claim_of(api, conversation_id) is None
    assert running.get(uuid.UUID(conversation_id)) is None


# --- 1.3 failure paths with nobody watching ---


async def failing_turn(api, reply: list, *more: list):
    """Send a message, leave after the first delta, let the turn end; return its id."""
    await api.ready()
    hold = Hold()
    reply.insert(2, hold)
    api.fake.queue(reply, *more)
    left = await leave_chat(api, "hello", after_first("delta"))
    assert left.names == ["conversation", "delta"]
    hold.release.set()
    await turns_settled()
    conversation_id = conversation_id_from(left)
    assert running.get(uuid.UUID(conversation_id)) is None
    assert await claim_of(api, conversation_id) is None
    return conversation_id


async def test_a_provider_error_mid_stream_is_stored_as_failed(async_api):
    conversation_id = await failing_turn(
        async_api, text_chunks("Half ", "an ans")[:-1] + [MidStreamFailure]
    )

    last = (await messages_of(async_api, conversation_id))[-1]
    assert (last.role, last.status, last.error_code) == (
        "assistant",
        "failed",
        ErrorCode.PROVIDER_UNREACHABLE,
    )
    assert last.content == "Half an ans"


async def test_a_reply_at_the_length_limit_is_stored_as_cut(async_api):
    conversation_id = await failing_turn(
        async_api, text_chunks("A long ", "answer that", finish_reason="length")
    )

    last = (await messages_of(async_api, conversation_id))[-1]
    assert (last.status, last.error_code, last.content) == (
        "cut",
        ErrorCode.OUTPUT_LIMIT_REACHED,
        "A long answer that",
    )


async def test_the_tool_round_limit_is_stored(async_api):
    conversation_id = await failing_turn(
        async_api,
        tool_round("search_thoughts", '{"query": "a"}', "call_1", text="Let me look. "),
        tool_round("search_thoughts", '{"query": "b"}', "call_2"),
        tool_round("search_thoughts", '{"query": "c"}', "call_3"),
    )

    messages = await messages_of(async_api, conversation_id)
    assert len(async_api.fake.chat_requests) == 3
    assert messages[-2].role == "assistant"
    assert messages[-2].error_code == ErrorCode.TOOL_LOOP_LIMIT


# --- 1.4 /compact frees the conversation when its client goes away ---


async def seed_long_conversation(api) -> str:
    """A conversation with ten messages, enough for /compact to replace some."""
    user_id = await api.user_id()

    async def seed(session):
        conversation = Conversation(
            user_id=user_id,
            title="Rent",
            last_activity_at=datetime.now(UTC),
            provider_id="nebius",
            model=NANO,
        )
        session.add(conversation)
        await session.flush()
        for position in range(10):
            session.add(
                Message(
                    conversation_id=conversation.id,
                    position=position,
                    role="user" if position % 2 == 0 else "assistant",
                    content=f"message {position}",
                )
            )
        await session.commit()
        return str(conversation.id)

    return await api.db(seed)


async def test_a_compact_draft_left_mid_call_frees_the_conversation_and_stores_nothing(async_api):
    api = async_api
    await api.ready()
    conversation_id = await seed_long_conversation(api)
    hold = Hold()
    api.fake.queue(text_chunks("We talked ")[:-1] + [hold] + text_chunks("about rent.") + [usage_chunk()])

    left = await leave_chat(api, "/compact", hold.reached, conversation_id)

    assert left.status == 200
    assert "compact_draft" not in left.names and "done" not in left.names
    assert len(api.fake.chat_requests) == 1
    assert await claim_of(api, conversation_id) is None
    messages = await messages_of(api, conversation_id)
    assert [(m.content, m.compacted) for m in messages] == [
        (f"message {n}", False) for n in range(10)
    ]
    assert await usage_rows(api) == []

    async def summaries(session):
        return (
            await session.execute(
                select(func.count()).select_from(Message).where(Message.role == "summary")
            )
        ).scalar_one()

    assert await api.db(summaries) == 0


# --- 2.1 following a running turn again ---


async def held_turn(api, message: str = "hello", conversation_id: str | None = None):
    """Send a message whose answer stops after "Hello " until `hold.release`
    is set; the sender leaves after the first delta. Return (id, hold)."""
    hold = Hold()
    api.fake.queue(text_chunks("Hello ")[:-1] + [hold] + text_chunks("there.") + [usage_chunk()])
    left = await leave_chat(api, message, after_first("delta"), conversation_id)
    assert left.status == 200
    if conversation_id is None:
        conversation_id = conversation_id_from(left)
    assert running.get(uuid.UUID(conversation_id)) is not None
    return conversation_id, hold


def stream_path(conversation_id: str) -> str:
    return f"/api/chat/{conversation_id}/stream"


async def test_the_owner_follows_a_running_turn_from_its_first_event(async_api):
    api = async_api
    await api.ready()
    conversation_id, hold = await held_turn(api)

    # A follower that leaves early got the answer so far, from the first event.
    early = await leave(
        api.app, stream_path(conversation_id), api.headers, None, after_first("delta"), method="GET"
    )
    assert early.status == 200
    assert early.headers["content-type"].startswith("text/event-stream")
    assert early.events == [
        ("conversation", {"id": conversation_id, "title": "hello"}),
        ("delta", {"text": "Hello "}),
    ]
    assert running.get(uuid.UUID(conversation_id)) is not None

    # A follower that stays gets the same start, then the rest, then done.
    following = asyncio.ensure_future(api.http.get(stream_path(conversation_id), headers=api.headers))
    await asyncio.sleep(0.05)
    assert not following.done()
    hold.release.set()
    response = await asyncio.wait_for(following, 5)
    await turns_settled()

    assert response.status_code == 200
    events = parse_events(response.text)
    assert events[:2] == early.events
    assert [name for name, _ in events] == ["conversation", "delta", "delta", "usage", "done"]
    assert events[2] == ("delta", {"text": "there."})
    assert await claim_of(api, conversation_id) is None


async def test_following_a_conversation_with_no_running_turn_answers_204(async_api):
    api = async_api
    await api.ready()
    api.fake.queue(text_chunks("Hi!") + [usage_chunk()])
    conversation_id = parse_events((await api.chat("hello")).text)[0][1]["id"]

    response = await api.http.get(stream_path(conversation_id), headers=api.headers)

    assert response.status_code == 204
    assert response.content == b""


async def test_another_users_turn_and_an_unknown_id_are_both_not_found(async_api, make_token):
    api = async_api
    await api.ready()
    conversation_id, hold = await held_turn(api)
    bob = {"Authorization": f"Bearer {make_token(sub='user|bob')}"}

    foreign = await api.http.get(stream_path(conversation_id), headers=bob)
    unknown = await api.http.get(stream_path(str(uuid.uuid4())), headers=api.headers)
    hold.release.set()
    await turns_settled()

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json() == {
        "error": {"code": ErrorCode.NOT_FOUND, "message": "Not found."}
    }


# --- 2.2 the conversation detail says a turn is running ---


async def detail_turn(api, conversation_id: str):
    response = await api.http.get(f"/api/conversations/{conversation_id}", headers=api.headers)
    assert response.status_code == 200, response.text
    return response.json()["turn"]


async def test_the_detail_carries_the_running_turn_while_it_runs(async_api):
    api = async_api
    await api.ready()
    conversation_id, hold = await held_turn(api)

    assert await detail_turn(api, conversation_id) == {"after_position": 0}
    hold.release.set()
    await turns_settled()
    assert await detail_turn(api, conversation_id) is None

    # The second message is stored after the first answer, at position 2.
    _, hold = await held_turn(api, "and more", conversation_id)
    assert await detail_turn(api, conversation_id) == {"after_position": 2}
    hold.release.set()
    await turns_settled()
    assert await detail_turn(api, conversation_id) is None
    positions = [(m.position, m.role) for m in await messages_of(api, conversation_id)]
    assert positions == [(0, "user"), (1, "assistant"), (2, "user"), (3, "assistant")]


async def test_a_compact_claim_is_not_a_running_turn(async_api):
    api = async_api
    await api.ready()
    conversation_id = await seed_long_conversation(api)
    hold = Hold()
    api.fake.queue(text_chunks("We talked ")[:-1] + [hold] + text_chunks("about rent.") + [usage_chunk()])
    gone = asyncio.Event()
    drafting = asyncio.ensure_future(leave_chat(api, "/compact", gone, conversation_id))
    await asyncio.wait_for(hold.reached.wait(), 5)

    assert await claim_of(api, conversation_id) is not None
    assert await detail_turn(api, conversation_id) is None
    follow = await api.http.get(stream_path(conversation_id), headers=api.headers)
    assert follow.status_code == 204

    gone.set()
    await drafting
    assert await claim_of(api, conversation_id) is None


# --- 3.1 a demo visitor's key lasts the whole turn, and goes nowhere else ---

DEMO_KEY = "nb-demo-held-key-7f3a9c"


@pytest.fixture
async def demo_api(test_database_url, settings_env):
    """async_api in demo mode: a demo visitor whose key is only in X-Provider-Keys."""
    import base64
    from datetime import timedelta

    import httpx

    from app.db import get_engine
    from app.main import app
    from app.providers import get_provider_http_client
    from tests.chat_helpers import PROVIDERS_FIXTURE, AsyncApi, FakeLLM, entry

    settings_env.setenv("AUTH_MODE", "demo")
    settings_env.delenv("OIDC_ISSUER")
    settings_env.delenv("OIDC_CLIENT_ID")
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    fake = FakeLLM()
    app.dependency_overrides[get_provider_http_client] = fake.http_client
    expires = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    held = json.dumps({"nebius": {"key": DEMO_KEY, "expires_at": expires}}).encode()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            session = await http.post("/api/demo/sessions")
            assert session.status_code == 201, session.text
            headers = {
                "Authorization": f"Bearer {session.json()['session']}",
                "X-Provider-Keys": base64.urlsafe_b64encode(held).rstrip(b"=").decode(),
            }
            api = AsyncApi(http, fake, headers)
            # Each request with the key runs in its own task, as in a server,
            # so the key never lands in the test's own context.
            response = await asyncio.create_task(
                http.put(
                    "/api/settings/models",
                    headers=headers,
                    json={"models": [entry(NANO, default=True)], "temperature": None},
                )
            )
            assert response.status_code == 200, response.text
            yield api
    finally:
        try:
            await turns_settled()
        finally:
            for turn in running.running_turns():
                if turn.task is not None:
                    turn.task.cancel()
            app.dependency_overrides.clear()
            await get_engine().dispose()


async def seed_thought_without_a_key(api) -> str:
    """A thought stored with no key at hand, so it has no embedding yet: the
    search embeds it, with the query, using the turn's key."""
    assert held_keys() == {}
    from app.config import get_settings
    from app.models import ThoughtEmbedding, User
    from app.thoughts.store import store_thought

    user_id = await asyncio.create_task(api.user_id())
    assert held_keys() == {}

    async def work(session):
        user = await session.get(User, user_id)
        outcome = await store_thought(
            session, user, title="Oat milk", summary="Buy oat milk on the way home.",
            tags=["groceries"], settings=get_settings(), http_client=api.fake.http_client(),
        )
        embedded = (
            await session.execute(select(func.count()).select_from(ThoughtEmbedding))
        ).scalar_one()
        assert embedded == 0
        return str(outcome.thought.id)

    thought_id = await api.db(work)
    assert not [r for r in api.fake.requests if r.url.path.endswith("/embeddings")]
    return thought_id


async def every_stored_value(api) -> str:
    """Every row of every table, as text."""
    from sqlalchemy import text

    from app.models import Base

    async def work(session):
        rows = []
        for table in Base.metadata.sorted_tables:
            result = await session.execute(text(f'SELECT * FROM "{table.name}"'))
            rows += [repr(tuple(row)) for row in result]
        return "\n".join(rows)

    return await api.db(work)


@pytest.mark.postgres
async def test_a_demo_turn_uses_the_held_key_after_its_client_disconnects(demo_api, caplog):
    api = demo_api
    thought_id = await seed_thought_without_a_key(api)
    hold = Hold()
    first = tool_round("search_thoughts", '{"query": "oat milk"}', "call_s", text="Let me look. ")
    # The stream stops after the first piece of text, before the tool call.
    first.insert(2, hold)
    api.fake.queue(first, text_chunks("You wanted oat milk.") + [usage_chunk()])
    calls_before = len(api.fake.requests)

    with caplog.at_level(logging.DEBUG):
        left = await asyncio.create_task(
            leave_chat(api, "/pull what did I want to buy?", after_first("delta"))
        )
        # The request is over and the key was only in its context.
        assert held_keys() == {}
        assert left.names == ["conversation", "delta"]
        conversation_id = conversation_id_from(left)
        turn = running.get(uuid.UUID(conversation_id))
        assert turn is not None
        # Nothing has searched yet: the browser left before the tool ran.
        assert not [r for r in api.fake.requests if r.url.path.endswith("/embeddings")]
        hold.release.set()
        await turns_settled()

    calls = api.fake.requests[calls_before:]
    chat_calls = [r for r in calls if r.url.path.endswith("/chat/completions")]
    embed_calls = [r for r in calls if r.url.path.endswith("/embeddings")]
    assert len(chat_calls) == 2 and len(embed_calls) == 1
    assert {r.headers["Authorization"] for r in chat_calls + embed_calls} == {f"Bearer {DEMO_KEY}"}

    messages = await messages_of(api, conversation_id)
    assert [m.role for m in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[0].content == "/pull what did I want to buy?"
    assert [s["id"] for s in messages[2].details["sources"]] == [thought_id]
    assert (messages[3].status, messages[3].content) == ("complete", "You wanted oat milk.")
    rows = await usage_rows(api)
    assert sorted(row.kind for row in rows) == ["chat", "chat", "embed"]
    assert all(row.conversation_id == uuid.UUID(conversation_id) for row in rows)
    assert await claim_of(api, conversation_id) is None

    # The key is in no table, no event of the turn's log, and no log line.
    assert DEMO_KEY not in await every_stored_value(api)
    assert turn.ended and turn.events[-1] == ("done", {})
    assert DEMO_KEY not in json.dumps(turn.events)
    assert DEMO_KEY not in repr(vars(turn))
    assert DEMO_KEY not in left.body
    assert caplog.records
    assert DEMO_KEY not in caplog.text
    assert all(DEMO_KEY not in record.getMessage() for record in caplog.records)
