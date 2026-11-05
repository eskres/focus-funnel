"""A turn runs to its end when its browser goes away, and a stopped server
leaves it failed and free (background-turns 1.2-4.2)."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.chat import running
from app.demo_keys import held_keys
from app.errors import ApiError, ErrorCode
from app.models import Conversation, Message, Proposal, UsageEvent
from tests.chat_helpers import (
    NANO,
    Hold,
    MidStreamFailure,
    api_error,
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


async def test_a_failure_opening_a_later_round_is_stored_as_failed(async_api):
    api = async_api
    # The provider refuses the second model call, every retry included.
    conversation_id = await failing_turn(
        api,
        tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Let me look. "),
        api_error(429),
        api_error(429),
        api_error(429),
    )

    messages = await messages_of(api, conversation_id)
    assert [m.role for m in messages] == ["user", "assistant", "tool", "assistant"]
    assert (messages[1].status, messages[1].content) == ("complete", "Let me look. ")
    assert (messages[-1].status, messages[-1].content, messages[-1].error_code) == (
        "failed",
        None,
        ErrorCode.PROVIDER_RATE_LIMITED,
    )
    response = await api.http.get(f"/api/conversations/{conversation_id}", headers=api.headers)
    assert response.json()["messages"][-1]["error_code"] == ErrorCode.PROVIDER_RATE_LIMITED


async def test_a_failing_tool_is_stored_as_failed_with_the_text_so_far(async_api, monkeypatch):
    from app.chat import turn as turn_module

    async def refused(*args, **kwargs):
        raise ApiError(503, ErrorCode.PROVIDER_UNREACHABLE, "The provider is unreachable.")

    monkeypatch.setattr(turn_module, "search_tool_result", refused)
    conversation_id = await failing_turn(
        async_api, tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Let me look. ")
    )

    messages = await messages_of(async_api, conversation_id)
    assert [m.role for m in messages] == ["user", "assistant", "assistant"]
    assert (messages[-1].status, messages[-1].error_code) == ("failed", ErrorCode.PROVIDER_UNREACHABLE)


async def test_a_failure_after_the_answer_is_stored_adds_nothing(async_api, monkeypatch):
    from app.chat.turn import Turn

    async def broken(self):
        raise RuntimeError("the meter broke")
        yield  # an async generator, like the method it replaces

    monkeypatch.setattr(Turn, "_suggest_compact", broken)
    conversation_id = await failing_turn(async_api, text_chunks("All ", "done.") + [usage_chunk()])

    messages = await messages_of(async_api, conversation_id)
    assert [(m.role, m.status, m.content) for m in messages] == [
        ("user", "complete", "hello"),
        ("assistant", "complete", "All done."),
    ]


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


async def test_a_follower_holds_no_database_connection_while_it_waits(async_api):
    from app.db import get_engine

    api = async_api
    await api.ready()
    conversation_id, hold = await held_turn(api)
    await asyncio.sleep(0.05)
    before = get_engine().pool.checkedout()

    following = asyncio.ensure_future(api.http.get(stream_path(conversation_id), headers=api.headers))
    await asyncio.sleep(0.1)
    during = get_engine().pool.checkedout()
    hold.release.set()
    response = await asyncio.wait_for(following, 5)
    await turns_settled()

    assert response.status_code == 200
    assert parse_events(response.text)[-1] == ("done", {})
    assert during == before


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


async def test_a_turn_that_ends_while_the_detail_loads_leaves_its_answer_in_it(
    async_api, monkeypatch
):
    from app.routers import conversations

    api = async_api
    await api.ready()
    conversation_id, hold = await held_turn(api)
    model_info = conversations.model_info

    async def turn_ends_meanwhile(*args, **kwargs):
        # The detail has read what it reads first; now the turn ends.
        hold.release.set()
        await turns_settled()
        return await model_info(*args, **kwargs)

    monkeypatch.setattr(conversations, "model_info", turn_ends_meanwhile)
    response = await api.http.get(f"/api/conversations/{conversation_id}", headers=api.headers)

    body = response.json()
    assert running.get(uuid.UUID(conversation_id)) is None
    # Never "no turn" with the answer missing: the turn was read first, and
    # following it now answers 204, so the chat loads the stored answer.
    assert [m["role"] for m in body["messages"]] == ["user"]
    assert body["turn"] == {"after_position": 0}
    follow = await api.http.get(stream_path(conversation_id), headers=api.headers)
    assert follow.status_code == 204


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
    # Asked while the draft holds its claim, not after it timed out.
    assert await asyncio.wait_for(detail_turn(api, conversation_id), 2) is None
    follow = await asyncio.wait_for(
        api.http.get(stream_path(conversation_id), headers=api.headers), 2
    )
    assert follow.status_code == 204
    assert await claim_of(api, conversation_id) is not None
    assert not drafting.done()

    gone.set()
    await drafting
    hold.release.set()
    assert await claim_of(api, conversation_id) is None


async def test_deleting_a_conversation_while_its_turn_runs_keeps_the_usage(async_api):
    api = async_api
    await api.ready()
    conversation_id, hold = await held_turn(api)
    turn = running.get(uuid.UUID(conversation_id))

    deleted = await api.http.delete(f"/api/conversations/{conversation_id}", headers=api.headers)
    assert deleted.status_code == 204
    hold.release.set()
    await turns_settled()

    # The call that was running is recorded, without its conversation, and
    # the turn makes no further call.
    [row] = await usage_rows(api)
    assert (row.kind, row.conversation_id, row.prompt_tokens) == ("chat", None, 100)
    assert len(api.fake.chat_requests) == 1
    assert turn.events[-1] == ("error", {"error": {"code": ErrorCode.NOT_FOUND, "message": "Not found."}})
    assert await messages_of(api, conversation_id) == []


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


# --- 4.1 shutdown stores the answer in flight as interrupted ---

INTERRUPTED = (
    "error",
    {
        "error": {
            "code": ErrorCode.ANSWER_INTERRUPTED,
            "message": "This answer did not finish. Send the message again to retry.",
        }
    },
)


async def watch_chat(api, message: str, conversation_id: str | None = None) -> asyncio.Task:
    """Send a message from a client that stays until the stream ends."""
    stay = asyncio.Event()
    return asyncio.create_task(leave_chat(api, message, stay, conversation_id))


async def test_a_cancelled_turn_stores_its_text_so_far_as_interrupted(async_api):
    api = async_api
    await api.ready()
    hold = Hold()
    reply = text_chunks("Half an ", "answer")
    # The stream stops after both pieces of text, before the reply ends.
    reply.insert(3, hold)
    api.fake.queue(reply)
    watcher = await watch_chat(api, "hello")
    await asyncio.wait_for(hold.reached.wait(), 5)
    [turn] = running.running_turns()
    conversation_id = str(turn.conversation_id)
    assert await claim_of(api, conversation_id) is not None

    turn.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(turn.task, 5)
    left = await asyncio.wait_for(watcher, 5)

    messages = await messages_of(api, conversation_id)
    assert [m.role for m in messages] == ["user", "assistant"]
    answer = messages[1]
    assert (answer.status, answer.content, answer.error_code) == (
        "failed",
        "Half an answer",
        ErrorCode.ANSWER_INTERRUPTED,
    )
    assert await claim_of(api, conversation_id) is None
    assert running.get(turn.conversation_id) is None
    # The client watching it learns the answer did not finish.
    assert left.names == ["conversation", "delta", "delta", "error"]
    assert left.events[-1] == INTERRUPTED == turn.events[-1]

    api.fake.queue(text_chunks("Here it is.") + [usage_chunk()])
    response = await api.chat("hello again", conversation_id)
    assert [name for name, _ in parse_events(response.text)] == ["delta", "usage", "done"]


async def test_a_turn_cancelled_after_a_tool_round_keeps_that_round(async_api):
    api = async_api
    await api.ready()
    hold = Hold()
    api.fake.queue(
        tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Let me look. "),
        # The second model call is open but has sent nothing yet.
        [hold] + text_chunks("Found nothing."),
    )
    watcher = await watch_chat(api, "what milk?")
    await asyncio.wait_for(hold.reached.wait(), 5)
    [turn] = running.running_turns()
    conversation_id = str(turn.conversation_id)

    turn.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(turn.task, 5)
    await asyncio.wait_for(watcher, 5)

    messages = await messages_of(api, conversation_id)
    assert [m.role for m in messages] == ["user", "assistant", "tool", "assistant"]
    # The stored round keeps its text; the interrupted one had none yet.
    assert (messages[1].status, messages[1].content) == ("complete", "Let me look. ")
    assert "sources" in messages[2].details
    assert (messages[3].status, messages[3].content, messages[3].error_code) == (
        "failed",
        None,
        ErrorCode.ANSWER_INTERRUPTED,
    )
    assert len(await usage_rows(api)) == 1
    assert await claim_of(api, conversation_id) is None


async def test_a_turn_cancelled_after_its_answer_is_stored_adds_no_failed_answer(
    async_api, monkeypatch
):
    from app.chat.turn import Turn

    api = async_api
    await api.ready()
    stored = asyncio.Event()

    async def after_the_answer(self):
        # The complete answer is committed; the turn is still running.
        stored.set()
        await asyncio.Event().wait()
        yield  # an async generator, like the method it replaces

    monkeypatch.setattr(Turn, "_suggest_compact", after_the_answer)
    api.fake.queue(text_chunks("All ", "done.") + [usage_chunk()])
    watcher = await watch_chat(api, "hello")
    await asyncio.wait_for(stored.wait(), 5)
    [turn] = running.running_turns()
    conversation_id = str(turn.conversation_id)

    turn.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(turn.task, 5)
    await asyncio.wait_for(watcher, 5)

    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content, m.error_code) for m in messages] == [
        ("user", "complete", "hello", None),
        ("assistant", "complete", "All done.", None),
    ]
    assert await claim_of(api, conversation_id) is None


async def test_the_lifespan_exit_interrupts_running_turns_and_frees_them(async_api):
    from app.main import app, lifespan

    api = async_api
    await api.ready()
    holds = [Hold(), Hold()]
    for hold in holds:
        reply = text_chunks("Part one, ", "never part two")
        reply.insert(2, hold)
        api.fake.queue(reply)

    async with lifespan(app):
        watchers = [await watch_chat(api, "first"), await watch_chat(api, "second")]
        for hold in holds:
            await asyncio.wait_for(hold.reached.wait(), 5)
        turns = running.running_turns()
        assert len(turns) == 2
    # The lifespan has returned: every turn has stored its answer and ended.

    assert running.running_turns() == []
    assert all(turn.ended and turn.events[-1] == INTERRUPTED for turn in turns)
    for turn in turns:
        conversation_id = str(turn.conversation_id)
        messages = await messages_of(api, conversation_id)
        assert [(m.role, m.status, m.content, m.error_code) for m in messages][1:] == [
            ("assistant", "failed", "Part one, ", ErrorCode.ANSWER_INTERRUPTED)
        ]
        assert await claim_of(api, conversation_id) is None
    for watcher in watchers:
        assert (await asyncio.wait_for(watcher, 5)).events[-1] == INTERRUPTED


# --- 4.2 the startup sweep frees what a stopped server left ---


def _seed(url, client, headers, messages, claimed: bool | str, **extra_last) -> str:
    """A conversation with these messages (alternating user and assistant),
    claimed or not; `extra_last` sets fields on the last message.

    `claimed=True` is a chat turn's claim, which sets the last activity when
    it stores its message; `claimed="compact"` is a claim that does not."""
    from sqlalchemy import update

    from tests.chat_helpers import run_db, seed_conversation

    conversation_id = seed_conversation(url, client, headers, messages=messages)

    async def work(session):
        if claimed:
            started = datetime.now(UTC)
            values = {"turn_started_at": started}
            if claimed is True:
                values["last_activity_at"] = started
            await session.execute(
                update(Conversation)
                .where(Conversation.id == uuid.UUID(conversation_id))
                .values(**values)
            )
        if extra_last:
            await session.execute(
                update(Message)
                .where(
                    Message.conversation_id == uuid.UUID(conversation_id),
                    Message.position == len(messages) - 1,
                )
                .values(**extra_last)
            )
        await session.commit()

    run_db(url, work)
    return conversation_id


def _state(url, conversation_id):
    from tests.chat_helpers import run_db

    async def work(session):
        conversation = await session.get(Conversation, uuid.UUID(conversation_id))
        rows = (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.position)
            )
        ).scalars()
        return conversation.turn_started_at, [
            (m.position, m.role, m.status, m.content, m.error_code) for m in rows
        ]

    return run_db(url, work)


def _sweep(url) -> int:
    from app.chat.conversations import release_stale_turns
    from tests.chat_helpers import run_db

    return run_db(url, release_stale_turns)


@pytest.mark.postgres
def test_the_sweep_stores_an_interrupted_answer_and_frees_the_claim(
    client, alice, test_database_url
):
    url = test_database_url
    unanswered = _seed(url, client, alice, ("hello", "Hi!", "and again"), claimed=True)
    mid_tools = _seed(
        url,
        client,
        alice,
        ("look it up", "Let me look."),
        claimed=True,
        tool_calls=[
            {"id": "call_s", "type": "function", "function": {"name": "search_thoughts", "arguments": "{}"}}
        ],
    )
    answered = _seed(url, client, alice, ("hello", "Hi!"), claimed=True)
    compacted = _seed(url, client, alice, ("hello", "Hi!", "Summary."), claimed=True, role="summary")
    free = _seed(url, client, alice, ("hello", "Hi!", "unanswered"), claimed=False)
    # A /compact draft over a message that got no answer (context_full).
    drafting = _seed(url, client, alice, ("hello", "Hi!", "too long"), claimed="compact")
    before = {cid: _state(url, cid) for cid in (answered, compacted, free, drafting)}

    assert _sweep(url) == 5

    claim, messages = _state(url, unanswered)
    assert claim is None
    assert messages[-1] == (3, "assistant", "failed", None, ErrorCode.ANSWER_INTERRUPTED)
    assert len(messages) == 4
    claim, messages = _state(url, mid_tools)
    assert claim is None
    assert messages[-1] == (2, "assistant", "failed", None, ErrorCode.ANSWER_INTERRUPTED)
    # A finished answer (or an accepted summary), or a claim that was not a
    # chat turn's, only gets its claim cleared.
    for conversation_id in (answered, compacted, drafting):
        claim, messages = _state(url, conversation_id)
        assert claim is None
        assert messages == before[conversation_id][1]
    # A conversation with no claim is untouched.
    assert _state(url, free) == before[free]
    # Run again, it has nothing left to do.
    assert _sweep(url) == 0

    response = client.get(f"/api/conversations/{unanswered}", headers=alice)
    assert response.json()["messages"][-1]["error_code"] == ErrorCode.ANSWER_INTERRUPTED


@pytest.mark.postgres
def test_the_app_runs_the_sweep_before_it_serves(
    test_database_url, jwks_cache, settings_env, alice, fake_llm
):
    from fastapi.testclient import TestClient

    from app.auth import get_jwks_cache
    from app.main import app
    from tests.chat_helpers import PROVIDERS_FIXTURE, chat, ready_user

    url = test_database_url
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    try:
        with TestClient(app) as client:
            ready_user(client, alice)
            # A server that stopped mid-turn left this claim.
            conversation_id = _seed(url, client, alice, ("hello", "Hi!", "again"), claimed=True)
            fake_llm.queue(text_chunks("Too soon."))
            assert chat(client, alice, "now?", conversation_id).status_code == 409

        with TestClient(app) as client:
            claim, messages = _state(url, conversation_id)
            assert claim is None
            assert messages[-1][1:] == ("assistant", "failed", None, ErrorCode.ANSWER_INTERRUPTED)
            # The conversation answers the next message at once.
            response = chat(client, alice, "again", conversation_id)
            assert response.status_code == 200
            assert parse_events(response.text)[-1] == ("done", {})
    finally:
        app.dependency_overrides.clear()
