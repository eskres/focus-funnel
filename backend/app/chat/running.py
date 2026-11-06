"""Running turns: a chat turn runs as a background task, not inside its response.

`POST /api/chat` opens the turn and hands it to `start`, which runs it as an
`asyncio` task and keeps a strong reference to it, keyed by conversation id.
The task appends every event to the turn's log and ends the log with the same
terminal event a stream sends (`done`, or `error` with its code). A response
is only a subscriber (`follow`): it replays the log from the start, then
follows it, and a dropped connection cancels the subscriber, never the turn.

The task copies the request's `contextvars` context when it is created, so
the demo held keys and the log-masking secrets the request set stay visible
to the turn for its whole run. Nothing about keys goes into the registry.

The registry lives in this process's memory: the backend runs as one process.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

import anyio

from app.chat.sse import DONE, Event, terminal_event
from app.errors import answer_interrupted

logger = logging.getLogger(__name__)

Settle = Callable[[], Awaitable[None]]

CancelReason = Literal["stop", "shutdown"]

# How long shutdown and `stop_turns` wait for turns to end. Read at call
# time, so a test can lower it.
STOP_WAIT_SECONDS = 5.0


@dataclass
class TurnControl:
    """What a running turn and its registry entry share (stop-and-spend-cap
    design decisions 1 and 3).

    The turn sets `interruptible` only while it awaits the next chunk of the
    model stream, opens a later round's call, or awaits a connector call that
    may reach its server, and checks `stop_requested` right before it sets
    the flag, with no await in between. `cancel_reason` is the reason of the
    one cancel the entry sent, so the turn knows a stop from a shutdown.
    """

    interruptible: bool = False
    stop_requested: bool = False
    cancel_reason: CancelReason | None = None


@dataclass(eq=False)
class RunningTurn:
    """One turn running in the background, and the events it has sent so far."""

    conversation_id: uuid.UUID
    user_id: uuid.UUID
    # The position of the user message the turn answers.
    after_position: int
    events: list[Event] = field(default_factory=list)
    ended: bool = False
    task: asyncio.Task | None = None
    # Shared with the turn: its stop flags and the reason of the cancel.
    control: TurnControl = field(default_factory=TurnControl)
    # A turn's task is cancelled at most once, by a stop or by shutdown.
    cancel_sent: bool = False
    # Set and replaced on every change, so a waiting subscriber wakes once.
    _changed: asyncio.Event = field(default_factory=asyncio.Event)

    def stop(self) -> None:
        """Ask the turn to stop. Never waits.

        The first call sets `stop_requested`; a later one does nothing more.
        The task is cancelled only while the turn is interruptible: anywhere
        else it sees the flag at its next check and ends there. The flag is
        read and the cancel sent in this one step, which no turn step can
        interleave with.
        """
        if self.ended or self.control.stop_requested:
            return
        self.control.stop_requested = True
        if self.control.interruptible and not self.cancel_sent:
            self._cancel("stop")

    def shutdown(self) -> None:
        """Cancel the turn for a server shutdown, unless it was already
        cancelled or is stopping: a turn that is stopping is only awaited."""
        if self.ended or self.cancel_sent or self.control.stop_requested:
            return
        self._cancel("shutdown")

    def _cancel(self, reason: CancelReason) -> None:
        if self.task is None:
            return
        self.cancel_sent = True
        self.control.cancel_reason = reason
        self.task.cancel()

    def append(self, event: Event) -> None:
        self.events.append(event)
        self._wake()

    def end(self, terminal: Event) -> None:
        self.events.append(terminal)
        self.ended = True
        self._wake()

    def _wake(self) -> None:
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()


_running: dict[uuid.UUID, RunningTurn] = {}
# Settle steps that outlived a cancelled caller; held so they are not collected.
_settling: set[asyncio.Task] = set()


def get(conversation_id: uuid.UUID) -> RunningTurn | None:
    """The conversation's running turn, if one runs in this process."""
    return _running.get(conversation_id)


def running_turns() -> list[RunningTurn]:
    return list(_running.values())


async def shielded(work: Awaitable[None]) -> None:
    """Run `work` to its end even when the caller is cancelled.

    `work` runs as its own task, so a cancelled caller stops waiting but the
    work goes on, in order, and nothing else touches what it uses. The anyio
    shield keeps a Starlette response's cancel scope (which cancels every
    await again until the scope exits) from interrupting the wait, so a
    response that is not cancelled from outside the scope waits for the end.
    """
    task = asyncio.ensure_future(work)
    _settling.add(task)
    task.add_done_callback(_settling.discard)
    with anyio.CancelScope(shield=True):
        await asyncio.shield(task)


def start(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    after_position: int,
    events: AsyncIterator[Event],
    settle: Settle,
    control: TurnControl | None = None,
) -> RunningTurn:
    """Run a turn's events in the background and return its registry entry.

    `settle` closes the model call, commits, releases the claim, and closes
    the session. It runs once the events end, however they end. `control`
    is the turn's own (`Turn.control`), so a stop reaches it.
    """
    turn = RunningTurn(conversation_id, user_id, after_position)
    if control is not None:
        turn.control = control
    _running[conversation_id] = turn
    turn.task = asyncio.create_task(_run(turn, events, settle))
    return turn


async def _run(turn: RunningTurn, events: AsyncIterator[Event], settle: Settle) -> None:
    terminal = DONE
    try:
        async for event in events:
            turn.append(event)
    except asyncio.CancelledError:
        # A cancel the turn did not turn into a stop (shutdown): its
        # followers learn it did not finish.
        terminal = terminal_event(answer_interrupted())
        raise
    except Exception as exc:
        # A stopped turn ends here too, with `answer_stopped`.
        terminal = terminal_event(exc)
    finally:
        await shielded(_settle(turn, settle, terminal))


async def _settle(turn: RunningTurn, settle: Settle, terminal: Event) -> None:
    """Free the conversation, then end the log.

    The terminal event goes out only after the claim is released, so a client
    that sees it can send the next message at once.
    """
    try:
        await settle()
    except Exception:
        logger.exception("Could not settle a chat turn")
    finally:
        # A new turn may already run in the conversation once the claim is free.
        if _running.get(turn.conversation_id) is turn:
            del _running[turn.conversation_id]
        turn.end(terminal)


async def follow(turn: RunningTurn) -> AsyncIterator[Event]:
    """Every event of the turn from the first, then the rest as they come.

    Stops after the terminal event. Cancelling it cancels only this wait.
    """
    index = 0
    while True:
        changed = turn._changed
        while index < len(turn.events):
            index += 1
            yield turn.events[index - 1]
        # The terminal event is always the last one in the log.
        if turn.ended:
            return
        await changed.wait()


async def shutdown(timeout: float | None = None) -> None:
    """Cancel every running turn and wait, at most `timeout` seconds
    (`STOP_WAIT_SECONDS` by default), for each to store its answer and
    release its claim.

    A turn that is stopping, or was cancelled already, is not cancelled
    again (`RunningTurn.shutdown`): it is only awaited. A turn left after the
    wait is left to the startup sweep of the next start.
    """
    # Let a turn started just now take its first step: a task cancelled
    # before it starts never runs its `finally`.
    await asyncio.sleep(0)
    turns = list(_running.values())
    for turn in turns:
        turn.shutdown()
    pending = {turn.task for turn in turns if turn.task is not None} | _settling
    if pending:
        # `wait`, not `wait_for`: a turn that runs over is not cancelled again.
        await asyncio.wait(pending, timeout=STOP_WAIT_SECONDS if timeout is None else timeout)


async def stop_turns(user_id: uuid.UUID, conversation_id: uuid.UUID | None = None) -> None:
    """Stop the user's running turns (or the one of that conversation), and
    wait, at most `STOP_WAIT_SECONDS`, for them to end (design decision 13).

    Each turn ends through its stopped store, which commits its answer and
    the round's usage while the conversation still exists. The wait sends no
    cancel of its own: a turn still running after it is left running, and the
    caller's claim then finds it busy.
    """
    turns = [
        turn
        for turn in _running.values()
        if turn.user_id == user_id
        and (conversation_id is None or turn.conversation_id == conversation_id)
    ]
    for turn in turns:
        turn.stop()
    tasks = {turn.task for turn in turns if turn.task is not None and not turn.task.done()}
    if tasks:
        await asyncio.wait(tasks, timeout=STOP_WAIT_SECONDS)
