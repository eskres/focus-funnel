"""The running-turn registry (background-turns 1.1)."""

import asyncio
import logging
import uuid

import pytest

from app.chat import running
from app.errors import ApiError, ErrorCode


@pytest.fixture(autouse=True)
def empty_registry():
    yield
    for turn in running.running_turns():
        if turn.task is not None:
            turn.task.cancel()
    running._running.clear()


class Script:
    """A turn's events, fed one at a time by the test, and a record of its settle."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.settled = False
        # Whether the entry was still registered while the settle ran.
        self.registered_while_settling: bool | None = None
        self.conversation_id = uuid.uuid4()

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    async def settle(self):
        await asyncio.sleep(0)
        self.registered_while_settling = running.get(self.conversation_id) is not None
        self.settled = True

    def start(self) -> running.RunningTurn:
        return running.start(self.conversation_id, uuid.uuid4(), 3, self.events(), self.settle)


async def collect(turn: running.RunningTurn) -> list:
    return [event async for event in running.follow(turn)]


DELTA_A = ("delta", {"text": "Hel"})
DELTA_B = ("delta", {"text": "lo"})


async def test_two_subscribers_get_the_same_events_in_order():
    script = Script()
    turn = script.start()
    first = asyncio.create_task(collect(turn))
    script.queue.put_nowait(DELTA_A)
    await asyncio.sleep(0.01)
    # The second subscriber joins late and still gets every event from the first.
    second = asyncio.create_task(collect(turn))
    script.queue.put_nowait(DELTA_B)
    script.queue.put_nowait(None)

    expected = [DELTA_A, DELTA_B, ("done", {})]
    assert await asyncio.wait_for(first, 2) == expected
    assert await asyncio.wait_for(second, 2) == expected
    # One who comes after the end still gets the whole log.
    assert await collect(turn) == expected


async def test_a_cancelled_subscriber_does_not_cancel_the_turn():
    script = Script()
    turn = script.start()
    watcher = asyncio.create_task(collect(turn))
    script.queue.put_nowait(DELTA_A)
    await asyncio.sleep(0.01)

    watcher.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watcher
    script.queue.put_nowait(DELTA_B)
    script.queue.put_nowait(None)
    await asyncio.wait_for(turn.task, 2)

    assert not turn.task.cancelled()
    assert turn.events == [DELTA_A, DELTA_B, ("done", {})]
    assert script.settled


async def test_an_api_error_ends_the_log_with_its_error_event():
    script = Script()
    turn = script.start()
    script.queue.put_nowait(DELTA_A)
    script.queue.put_nowait(ApiError(502, ErrorCode.PROVIDER_UNREACHABLE, "No answer."))

    events = await asyncio.wait_for(collect(turn), 2)

    assert events == [
        DELTA_A,
        ("error", {"error": {"code": ErrorCode.PROVIDER_UNREACHABLE, "message": "No answer."}}),
    ]
    assert script.settled


async def test_any_other_error_ends_the_log_with_internal_error(caplog):
    script = Script()
    turn = script.start()
    script.queue.put_nowait(RuntimeError("secret detail"))

    with caplog.at_level(logging.ERROR):
        events = await asyncio.wait_for(collect(turn), 2)

    assert events == [
        ("error", {"error": {"code": ErrorCode.INTERNAL_ERROR, "message": "Something went wrong."}})
    ]
    assert "secret detail" not in str(events)
    assert "secret detail" in caplog.text
    assert script.settled


async def test_the_entry_is_gone_after_the_turn_ends_and_settles_first():
    script = Script()
    turn = script.start()
    assert running.get(script.conversation_id) is turn
    assert turn.after_position == 3

    script.queue.put_nowait(None)
    events = await asyncio.wait_for(collect(turn), 2)

    assert running.get(script.conversation_id) is None
    assert turn.ended and events[-1] == ("done", {})
    # Settled while the entry was still there, and before the terminal event.
    assert script.registered_while_settling is True


async def test_a_failing_settle_still_ends_the_log_and_removes_the_entry():
    script = Script()

    async def broken_settle():
        raise RuntimeError("database gone")

    turn = running.start(script.conversation_id, uuid.uuid4(), 0, script.events(), broken_settle)
    script.queue.put_nowait(None)

    assert await asyncio.wait_for(collect(turn), 2) == [("done", {})]
    assert running.get(script.conversation_id) is None


async def test_a_newer_turn_in_the_conversation_keeps_its_entry():
    script = Script()
    old = script.start()
    newer = running.start(script.conversation_id, uuid.uuid4(), 5, Script().events(), script.settle)

    script.queue.put_nowait(None)
    await asyncio.wait_for(old.task, 2)

    assert running.get(script.conversation_id) is newer
    newer.task.cancel()


async def test_the_settle_runs_to_its_end_when_its_caller_is_cancelled():
    steps = []
    gate = asyncio.Event()

    async def work():
        steps.append("started")
        await gate.wait()
        steps.append("finished")

    caller = asyncio.create_task(running.shielded(work()))
    await asyncio.sleep(0.01)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    gate.set()
    await asyncio.sleep(0.01)

    assert steps == ["started", "finished"]
