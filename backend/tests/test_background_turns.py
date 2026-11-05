"""A turn runs to its end when its browser goes away (background-turns 1.2-1.4)."""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.chat import running
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


async def test_a_compact_draft_left_mid_call_frees_the_conversation_and_stores_nothing(async_api):
    api = async_api
    await api.ready()
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

    conversation_id = await api.db(seed)
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
