"""Helpers for the Stop tests (stop-and-spend-cap group 3), loaded as a
pytest plugin from conftest.py.

- `cancel_spy`: every task created while it is on counts its `cancel()`
  calls, so a test can see how often a turn's task was cancelled.
- `block_commit`: makes `AsyncSession.commit` wait on an event while the
  session holds the rows a test names, so a stop can land during that store.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import running
from app.errors import ErrorCode
from app.models import Message

STOPPED = (
    "error",
    {"error": {"code": ErrorCode.ANSWER_STOPPED, "message": "You stopped this answer."}},
)


class SpyTask(asyncio.Task):
    """A task that counts how often it was cancelled."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cancels = 0

    def cancel(self, msg=None):
        self.cancels += 1
        return super().cancel(msg)


@pytest.fixture
async def cancel_spy():
    """Count every cancel of the tasks created from now on (a turn's task
    among them). `cancel_spy(turn)` gives the count for a running turn."""
    loop = asyncio.get_running_loop()
    previous = loop.get_task_factory()
    loop.set_task_factory(lambda loop, coro, **kwargs: SpyTask(coro, loop=loop, **kwargs))
    try:
        yield lambda turn: turn.task.cancels
    finally:
        loop.set_task_factory(previous)


@dataclass
class BlockedCommit:
    """A commit held while the session holds the rows `match` names."""

    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    # How many commits were held.
    held: int = 0

    async def reached(self, timeout: float = 5) -> None:
        await asyncio.wait_for(self.entered.wait(), timeout)


@pytest.fixture
def block_commit(monkeypatch):
    """`block_commit(match)`: from now on, a commit whose session makes
    `match(sync_session)` true waits until `.release` is set; `.entered` is
    set when the first one is held. Only the first matching commit waits."""

    def install(match: Callable) -> BlockedCommit:
        blocked = BlockedCommit()
        original = AsyncSession.commit

        async def commit(self):
            if blocked.held == 0 and match(self.sync_session):
                blocked.held += 1
                blocked.entered.set()
                await asyncio.wait_for(blocked.release.wait(), 10)
            return await original(self)

        monkeypatch.setattr(AsyncSession, "commit", commit)
        return blocked

    return install


def adding(**fields) -> Callable:
    """Match a session about to insert a message with these fields."""

    def match(session) -> bool:
        return any(
            isinstance(row, Message) and all(getattr(row, k) == v for k, v in fields.items())
            for row in session.new
        )

    return match


def changing(**fields) -> Callable:
    """Match a session about to update a message to these fields."""

    def match(session) -> bool:
        return any(
            isinstance(row, Message) and all(getattr(row, k) == v for k, v in fields.items())
            for row in session.dirty
        )

    return match


def the_turn() -> running.RunningTurn:
    [turn] = running.running_turns()
    return turn


async def stopped_messages(api, conversation_id: str) -> list[Message]:
    async def work(session):
        return list(
            (
                await session.execute(
                    select(Message).where(
                        Message.conversation_id == uuid.UUID(conversation_id),
                        Message.status == "stopped",
                    )
                )
            ).scalars()
        )

    return await api.db(work)


async def ended(turn: running.RunningTurn, timeout: float = 5) -> None:
    """Wait until the turn's task has finished, however it ended."""
    await asyncio.wait({turn.task}, timeout=timeout)
    assert turn.task.done()
