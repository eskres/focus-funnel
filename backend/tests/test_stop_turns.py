"""Stop on the running-turn registry (stop-and-spend-cap task 3.1).

A stop cancels the turn's task only while it waits for the model (a region);
anywhere else it is seen at the turn's next check. A turn's task is
cancelled at most once, and a stop never replaces how a turn already ended.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.chat import running
from app.chat import turn as turn_module
from app.chat.turn import Turn
from app.errors import ErrorCode
from app.models import UsageEvent
from tests.chat_helpers import (
    Hold,
    MidStreamFailure,
    text_chunks,
    turns_settled,
    usage_chunk,
)
from tests.sse_helpers import parse_events
from tests.stop_helpers import (
    STOPPED,
    adding,
    changing,
    ended,
    stopped_messages,
    the_turn,
)
from tests.test_background_turns import (
    INTERRUPTED,
    claim_of,
    messages_of,
    stream_path,
    tool_round,
    watch_chat,
)


async def start(api, reply: list, message: str = "hello", conversation_id: str | None = None):
    """Send a message whose stream waits at a Hold in `reply`; return
    (watcher, turn, conversation id) once the stream is held."""
    hold = next(item for item in reply if isinstance(item, Hold))
    api.fake.queue(reply)
    watcher = await watch_chat(api, message, conversation_id)
    await asyncio.wait_for(hold.reached.wait(), 5)
    turn = the_turn()
    return watcher, turn, str(turn.conversation_id), hold


async def put_cap(api, amount="5"):
    response = await api.http.put(
        "/api/usage/cap", headers=api.headers, json={"cap": {"unit": "usd", "amount": amount}}
    )
    assert response.status_code == 200, response.text


async def add_cost(api, cost: str) -> None:
    user_id = await api.user_id()

    async def work(session):
        session.add(
            UsageEvent(
                user_id=user_id,
                kind="chat",
                provider_id="nebius",
                model="vendor/nano-model",
                prompt_tokens=100,
                completion_tokens=10,
                cost_usd=Decimal(cost),
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    await api.db(work)


def requests_messages(api, index: int) -> list[dict]:
    return api.fake.chat_requests[index]["messages"]


# --- a stop in the stream ---


async def test_a_stop_after_two_deltas_keeps_them_and_ends_every_subscriber(
    async_api, cancel_spy
):
    api = async_api
    await api.ready()
    reply = text_chunks("Half an ", "answer", " never sent")
    # The stream waits after its two pieces of text.
    reply.insert(3, Hold())
    watcher, turn, conversation_id, _ = await start(api, reply)
    follower = asyncio.ensure_future(
        api.http.get(stream_path(conversation_id), headers=api.headers)
    )
    await asyncio.sleep(0.05)

    turn.stop()
    left = await asyncio.wait_for(watcher, 5)
    followed = await asyncio.wait_for(follower, 5)
    await turns_settled()

    assert cancel_spy(turn) == 1
    assert left.names == ["conversation", "delta", "delta", "error"]
    assert left.events[-1] == STOPPED
    assert parse_events(followed.text)[-1] == STOPPED
    assert turn.events[-1] == STOPPED
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content, m.error_code) for m in messages] == [
        ("user", "complete", "hello", None),
        ("assistant", "stopped", "Half an answer", ErrorCode.ANSWER_STOPPED),
    ]
    assert messages[1].details is None
    # The provider's response was closed and no other call was made.
    assert api.fake.streams[0].closed
    assert len(api.fake.chat_requests) == 1
    await asyncio.sleep(0.05)
    assert len(api.fake.chat_requests) == 1
    assert await claim_of(api, conversation_id) is None
    assert running.get(turn.conversation_id) is None

    # The next turn's context holds the stopped text as the assistant's.
    api.fake.queue(text_chunks("Go on.") + [usage_chunk()])
    response = await api.chat("go on", conversation_id)
    assert response.status_code == 200
    assert parse_events(response.text)[-1] == ("done", {})
    sent = requests_messages(api, 1)
    assert {"role": "assistant", "content": "Half an answer"} in sent
    assert [m["role"] for m in sent[-3:]] == ["user", "assistant", "user"]


async def test_a_stop_before_any_delta_stores_an_empty_stopped_answer_the_model_never_sees(
    async_api, cancel_spy
):
    api = async_api
    await api.ready()
    watcher, turn, conversation_id, _ = await start(api, [Hold()] + text_chunks("Never."))

    turn.stop()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 1
    assert left.names == ["conversation", "error"]
    assert left.events[-1] == STOPPED
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content, m.error_code) for m in messages] == [
        ("user", "complete", "hello", None),
        ("assistant", "stopped", None, ErrorCode.ANSWER_STOPPED),
    ]
    assert api.fake.streams[0].closed

    api.fake.queue(text_chunks("Hi.") + [usage_chunk()])
    response = await api.chat("hello again", conversation_id)
    assert parse_events(response.text)[-1] == ("done", {})
    sent = requests_messages(api, 1)
    assert [m["role"] for m in sent if m["role"] != "system"] == ["user", "user"]


# --- a stop outside a region waits for the next check ---


async def test_a_stop_during_the_cap_check_sends_no_cancel_and_opens_no_call(
    async_api, cancel_spy, monkeypatch
):
    api = async_api
    await api.ready()
    await put_cap(api, "100")
    entered, gate = asyncio.Event(), asyncio.Event()
    real_cap_state = turn_module.cap_state

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.wait_for(gate.wait(), 5)
        return await real_cap_state(*args, **kwargs)

    monkeypatch.setattr(turn_module, "cap_state", blocked)
    api.fake.queue(
        tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Let me look. "),
        text_chunks("Never asked.") + [usage_chunk()],
    )
    watcher = await watch_chat(api, "what milk?")
    await asyncio.wait_for(entered.wait(), 5)
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    await asyncio.sleep(0.05)
    assert cancel_spy(turn) == 0
    assert not turn.ended
    gate.set()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 0
    assert len(api.fake.chat_requests) == 1
    assert left.events[-1] == STOPPED
    assert [name for name, _ in left.events].count("tool") == 2
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content) for m in messages] == [
        ("user", "complete", "what milk?"),
        ("assistant", "complete", "Let me look. "),
        ("tool", "complete", messages[2].content),
        ("assistant", "stopped", None),
    ]
    assert "sources" in messages[2].details
    assert messages[3].error_code == ErrorCode.ANSWER_STOPPED
    assert await claim_of(api, conversation_id) is None


async def test_a_stop_while_the_complete_answer_is_stored_leaves_it_complete(
    async_api, cancel_spy, block_commit
):
    api = async_api
    await api.ready()
    blocked = block_commit(adding(role="assistant", status="complete", content="All done."))
    api.fake.queue(text_chunks("All ", "done.") + [usage_chunk()])
    watcher = await watch_chat(api, "hello")
    await blocked.reached()
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    assert cancel_spy(turn) == 0
    blocked.release.set()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 0
    assert left.events[-1] == ("done", {})
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content) for m in messages] == [
        ("user", "complete", "hello"),
        ("assistant", "complete", "All done."),
    ]
    assert await stopped_messages(api, conversation_id) == []
    assert await claim_of(api, conversation_id) is None


async def test_a_stop_while_the_tool_round_limit_is_stored_keeps_that_end(
    async_api, cancel_spy, block_commit, monkeypatch
):
    api = async_api
    await api.ready()
    init = Turn.__init__

    def one_round(self, *args, **kwargs):
        init(self, *args, **{**kwargs, "tool_rounds": 1})

    monkeypatch.setattr(Turn, "__init__", one_round)
    blocked = block_commit(changing(error_code=ErrorCode.TOOL_LOOP_LIMIT))
    api.fake.queue(tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Look. "))
    watcher = await watch_chat(api, "what milk?")
    await blocked.reached()
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    assert cancel_spy(turn) == 0
    blocked.release.set()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 0
    assert left.events[-1][0] == "error"
    assert left.events[-1][1]["error"]["code"] == ErrorCode.TOOL_LOOP_LIMIT
    messages = await messages_of(api, conversation_id)
    assert [m.role for m in messages] == ["user", "assistant", "tool"]
    assert messages[1].error_code == ErrorCode.TOOL_LOOP_LIMIT
    assert await stopped_messages(api, conversation_id) == []


async def test_a_stop_while_the_spend_cap_end_is_stored_keeps_that_end(
    async_api, cancel_spy, block_commit
):
    api = async_api
    await api.ready()
    await put_cap(api, "5")
    # Round 1's usage (100 and 20 tokens of NANO, $0.0000108) reaches it.
    await add_cost(api, "4.99999")
    blocked = block_commit(changing(error_code=ErrorCode.SPEND_CAP_REACHED))
    api.fake.queue(
        tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Look. "),
        text_chunks("Never asked.") + [usage_chunk()],
    )
    watcher = await watch_chat(api, "what milk?")
    await blocked.reached()
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    assert cancel_spy(turn) == 0
    blocked.release.set()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 0
    assert left.events[-1][1]["error"]["code"] == ErrorCode.SPEND_CAP_REACHED
    assert len(api.fake.chat_requests) == 1
    messages = await messages_of(api, conversation_id)
    assert [m.role for m in messages] == ["user", "assistant", "tool"]
    assert messages[1].error_code == ErrorCode.SPEND_CAP_REACHED
    assert await stopped_messages(api, conversation_id) == []


async def test_a_stop_while_a_failure_is_stored_keeps_the_providers_code(
    async_api, cancel_spy, block_commit
):
    api = async_api
    await api.ready()
    blocked = block_commit(adding(role="assistant", status="failed"))
    api.fake.queue(text_chunks("Half ", "an ans")[:-1] + [MidStreamFailure])
    watcher = await watch_chat(api, "hello")
    await blocked.reached()
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    assert cancel_spy(turn) == 0
    blocked.release.set()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 0
    assert left.events[-1][1]["error"]["code"] == ErrorCode.PROVIDER_UNREACHABLE
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content, m.error_code) for m in messages][1:] == [
        ("assistant", "failed", "Half an ans", ErrorCode.PROVIDER_UNREACHABLE)
    ]
    assert await stopped_messages(api, conversation_id) == []


# --- shutdown and stop: one cancel at most ---


async def test_a_shutdown_cancel_is_still_interrupted_and_a_later_stop_sends_no_cancel(
    async_api, cancel_spy
):
    api = async_api
    await api.ready()
    reply = text_chunks("Part one, ", "never part two")
    reply.insert(2, Hold())
    watcher, turn, conversation_id, _ = await start(api, reply)

    turn.shutdown()
    turn.stop()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(turn.task, 5)
    left = await asyncio.wait_for(watcher, 5)

    assert cancel_spy(turn) == 1
    assert turn.control.cancel_reason == "shutdown"
    assert left.events[-1] == INTERRUPTED == turn.events[-1]
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content, m.error_code) for m in messages][1:] == [
        ("assistant", "failed", "Part one, ", ErrorCode.ANSWER_INTERRUPTED)
    ]
    assert await stopped_messages(api, conversation_id) == []
    assert await claim_of(api, conversation_id) is None


async def test_the_lifespan_exit_waits_for_a_stopping_turn_and_sends_no_second_cancel(
    async_api, cancel_spy, block_commit, caplog
):
    from app.main import app, lifespan

    api = async_api
    await api.ready()
    blocked = block_commit(adding(role="assistant", status="stopped"))
    reply = text_chunks("Part one, ", "never part two")
    reply.insert(2, Hold())

    with caplog.at_level(logging.DEBUG):
        async with lifespan(app):
            watcher, turn, conversation_id, _ = await start(api, reply)
            turn.stop()
            await blocked.reached()
            assert cancel_spy(turn) == 1
            # The store goes on a moment after the lifespan exit has started.
            asyncio.get_running_loop().call_later(0.2, blocked.release.set)
        # The lifespan has returned: it waited for the stopping turn.
        assert turn.task.done()
        left = await asyncio.wait_for(watcher, 5)

    assert cancel_spy(turn) == 1
    assert left.events[-1] == STOPPED
    stopped = await stopped_messages(api, conversation_id)
    assert [(m.content, m.error_code) for m in stopped] == [
        ("Part one, ", ErrorCode.ANSWER_STOPPED)
    ]
    messages = await messages_of(api, conversation_id)
    assert [m.status for m in messages] == ["complete", "stopped"]
    assert await claim_of(api, conversation_id) is None
    assert running.running_turns() == []
    text = caplog.text
    for problem in (
        "concurrent operations",
        "IllegalStateChangeError",
        "provisioning a new connection",
        "MissingGreenlet",
        "Could not",
    ):
        assert problem not in text


async def test_the_lifespan_exit_sends_no_cancel_to_a_turn_stopping_outside_a_region(
    async_api, cancel_spy, monkeypatch, caplog
):
    """A stop during the cap check sends no cancel (the turn is not
    interruptible there); a shutdown then only waits for it, through the
    `stop_requested` guard of `RunningTurn.shutdown()` (decision 1)."""
    from app.main import app, lifespan

    api = async_api
    await api.ready()
    await put_cap(api, "100")
    entered, gate = asyncio.Event(), asyncio.Event()
    real_cap_state = turn_module.cap_state

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.wait_for(gate.wait(), 5)
        return await real_cap_state(*args, **kwargs)

    monkeypatch.setattr(turn_module, "cap_state", blocked)
    api.fake.queue(
        tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Let me look. "),
        text_chunks("Never asked.") + [usage_chunk()],
    )

    with caplog.at_level(logging.DEBUG):
        async with lifespan(app):
            watcher = await watch_chat(api, "what milk?")
            await asyncio.wait_for(entered.wait(), 5)
            turn = the_turn()
            conversation_id = str(turn.conversation_id)
            turn.stop()
            await asyncio.sleep(0.05)
            assert cancel_spy(turn) == 0
            assert not turn.ended
            # The cap check returns a moment after the lifespan exit started.
            asyncio.get_running_loop().call_later(0.2, gate.set)
        # The lifespan has returned: it waited for the stopping turn.
        assert turn.task.done()
        left = await asyncio.wait_for(watcher, 5)

    assert cancel_spy(turn) == 0
    assert turn.control.cancel_reason is None
    assert left.events[-1] == STOPPED
    assert len(api.fake.chat_requests) == 1
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status) for m in messages] == [
        ("user", "complete"),
        ("assistant", "complete"),
        ("tool", "complete"),
        ("assistant", "stopped"),
    ]
    assert messages[3].error_code == ErrorCode.ANSWER_STOPPED
    assert await claim_of(api, conversation_id) is None
    assert running.running_turns() == []
    assert "concurrent operations" not in caplog.text


async def test_a_second_stop_does_nothing_more(async_api, cancel_spy):
    api = async_api
    await api.ready()
    reply = text_chunks("Half ", "an answer")
    reply.insert(2, Hold())
    watcher, turn, conversation_id, _ = await start(api, reply)

    turn.stop()
    turn.stop()
    left = await asyncio.wait_for(watcher, 5)
    await ended(turn)
    turn.stop()

    assert cancel_spy(turn) == 1
    assert left.events[-1] == STOPPED
    assert len(await stopped_messages(api, conversation_id)) == 1
    assert uuid.UUID(conversation_id) == turn.conversation_id


async def test_a_stop_found_by_the_check_between_chunks_closes_the_stream(
    async_api, cancel_spy
):
    api = async_api
    await api.ready()
    reply = text_chunks("Half ", "an answer", " never read")
    hold = Hold()
    reply.insert(2, hold)
    watcher, turn, conversation_id, _ = await start(api, reply)

    # As if the stop had come while the turn handled a chunk: no cancel, and
    # the check before the next wait finds it.
    turn.control.stop_requested = True
    hold.release.set()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 0
    assert left.events[-1] == STOPPED
    stopped = await stopped_messages(api, conversation_id)
    # The chunk that was being awaited when the flag was set is kept.
    assert [m.content for m in stopped] == ["Half an answer"]
    assert api.fake.streams[0].closed
