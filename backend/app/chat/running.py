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

import anyio

from app.chat.sse import DONE, Event, terminal_event
from app.errors import ErrorCode

logger = logging.getLogger(__name__)

Settle = Callable[[], Awaitable[None]]


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
    # Set and replaced on every change, so a waiting subscriber wakes once.
    _changed: asyncio.Event = field(default_factory=asyncio.Event)

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
) -> RunningTurn:
    """Run a turn's events in the background and return its registry entry.

    `settle` closes the model call, commits, releases the claim, and closes
    the session. It runs once the events end, however they end.
    """
    turn = RunningTurn(conversation_id, user_id, after_position)
    _running[conversation_id] = turn
    turn.task = asyncio.create_task(_run(turn, events, settle))
    return turn


async def _run(turn: RunningTurn, events: AsyncIterator[Event], settle: Settle) -> None:
    terminal = DONE
    try:
        async for event in events:
            turn.append(event)
    except asyncio.CancelledError:
        terminal = (
            "error",
            {"error": {"code": ErrorCode.INTERNAL_ERROR, "message": "Something went wrong."}},
        )
        raise
    except Exception as exc:
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
