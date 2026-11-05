"""Actions: calls to acts tools that wait for the user's approval.

Openspec mcp-connectors design decisions 7 and 19. When the model calls an
acts tool that needs approval, the turn stores a `tool_actions` row instead
of calling the server, sends an `action` event for the card, and tells the
model the action has not run. The user approves or declines the card
(app/routers/actions.py). A turn that starts expires every action still
pending or failed, waits for one still running, and passes the outcome of
finished actions to the model as a note after the action's tool-call group
(`outcome_note`, placed by `build_context`).
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ConnectorLimits
from app.errors import ErrorCode
from app.mcp_client import mark_data
from app.models import Connector, Message, ToolAction

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
DECLINED = "declined"
EXPIRED = "expired"
# Approved, and the call was sent, but no outcome came back (it timed out,
# lost its connection, or the approval was interrupted): it may have run, so
# it is neither failed nor open to a second approval.
UNKNOWN = "unknown"

# A pending or failed action may still be approved or declined.
OPEN = (PENDING, FAILED)

# error_code of a done action whose server answered with an isError result:
# the tool ran and reported an error, which is the server's data.
TOOL_ERROR = "tool_error"

# What the model reads instead of a result (decision 7).
ACTION_SHOWN = (
    "The action is shown to the user to approve. It has not run. Do not say it ran or "
    "will run; say it is waiting for their approval. Do not call it again in this turn."
)


@dataclass(frozen=True)
class ActionTarget:
    """What a card names: the connector and the tool the model called."""

    connector_id: uuid.UUID
    connector_name: str
    tool: str
    title: str | None


def action_payload(action: ToolAction, title: str | None = None) -> dict[str, Any]:
    """An action as the `action` event, the conversation details, and the
    approval route send it."""
    return {
        "id": str(action.id),
        "position": action.position,
        "connector_id": str(action.connector_id) if action.connector_id else None,
        "connector": action.connector_name,
        "tool": action.tool,
        "title": title,
        "arguments": action.arguments,
        "status": action.status,
        "result": action.result,
        "error_code": action.error_code,
    }


def new_action(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    target: ActionTarget,
    arguments: dict[str, Any],
    position: int,
) -> ToolAction:
    return ToolAction(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        user_id=user_id,
        connector_id=target.connector_id,
        connector_name=target.connector_name,
        position=position,
        tool=target.tool,
        arguments=arguments,
        status=PENDING,
    )


async def list_actions(session: AsyncSession, conversation_id: uuid.UUID) -> list[ToolAction]:
    return list(
        (
            await session.execute(
                select(ToolAction)
                .where(ToolAction.conversation_id == conversation_id)
                .order_by(ToolAction.position, ToolAction.created_at)
            )
        )
        .scalars()
        .all()
    )


# How often a request waiting for a running action looks again.
POLL_SECONDS = 0.1
INTERRUPTED = "The approval was interrupted."


def running_limit(limits: ConnectorLimits) -> float:
    """The longest an approval's server call can take, in seconds: the
    connect, the call, and closing the session (bounded like the connect),
    plus a second to store the outcome. A request that is still alive stores
    its outcome within it, so a row running for longer lost its request."""
    return 2 * limits.connect_seconds + limits.call_seconds + 1


async def settle_stale(
    session: AsyncSession, conversation_id: uuid.UUID, limits: ConnectorLimits
) -> None:
    """A running action older than `running_limit` lost its request (the
    server restarted or was killed mid-call): it becomes unknown, so it is
    not stuck running for good. Not committed."""
    cutoff = datetime.now(UTC) - timedelta(seconds=running_limit(limits))
    await session.execute(
        update(ToolAction)
        .where(
            ToolAction.conversation_id == conversation_id,
            ToolAction.status == RUNNING,
            ToolAction.updated_at < cutoff,
        )
        .values(
            status=UNKNOWN,
            result=INTERRUPTED,
            error_code=ErrorCode.INTERNAL_ERROR,
            updated_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )


async def wait_for_running(
    session: AsyncSession, conversation_id: uuid.UUID, limits: ConnectorLimits
) -> None:
    """Wait until no action of the conversation is running, so the turn
    that starts gets its outcome (a turn and an approval never overlap).
    Commits; bounded by `running_limit`, after which a row still running is
    settled as unknown."""
    while True:
        await settle_stale(session, conversation_id, limits)
        await session.commit()
        running = (
            await session.execute(
                select(
                    exists().where(
                        ToolAction.conversation_id == conversation_id,
                        ToolAction.status == RUNNING,
                    )
                )
            )
        ).scalar_one()
        if not running:
            return
        # End the read transaction, so the next look sees the approval's commit.
        await session.commit()
        await asyncio.sleep(POLL_SECONDS)


async def expire_actions(session: AsyncSession, conversation_id: uuid.UUID) -> None:
    """A turn starts: every pending or failed action of the conversation
    expires. A running one finishes as it would. Not committed: the caller
    commits it with the turn's user message."""
    await session.execute(
        update(ToolAction)
        .where(ToolAction.conversation_id == conversation_id, ToolAction.status.in_(OPEN))
        .values(status=EXPIRED)
        .execution_options(synchronize_session=False)
    )


async def moved_on(session: AsyncSession, action: ToolAction) -> bool:
    """True when a user message came after the action: its turn is over, even
    if no turn expired it (one ran while connectors were off)."""
    return bool(
        (
            await session.execute(
                select(
                    exists().where(
                        Message.conversation_id == action.conversation_id,
                        Message.role == "user",
                        Message.position > action.position,
                    )
                )
            )
        ).scalar_one()
    )


async def move(session: AsyncSession, action: ToolAction, status: str) -> bool:
    """Move an open (pending or failed) action to `status` and commit.

    One conditional update, so of two requests only one wins, on SQLite and
    on Postgres alike. Reloads the row either way. updated_at is set here, so
    `settle_stale` can tell how long an action has been running.
    """
    result = await session.execute(
        update(ToolAction)
        .where(ToolAction.id == action.id, ToolAction.status.in_(OPEN))
        .values(status=status, updated_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    await session.refresh(action)
    return result.rowcount == 1


def outcome_note(action: ToolAction) -> str | None:
    """What the next turn's model reads about a finished action (done,
    unknown, declined, or expired), or None while it is pending or running
    (decision 7)."""
    name = f"{action.connector_name}__{action.tool}"
    if action.status == DONE:
        data = mark_data(
            action.connector_name,
            action.tool,
            action.result or "",
            is_error=action.error_code == TOOL_ERROR,
        )
        return f"The user approved {name}. It ran and returned:\n{data}"
    if action.status == UNKNOWN:
        return (
            f"The user approved {name}, but it is not known whether it ran: "
            f"{action.result or action.error_code} Do not say it ran or did not run, "
            "and do not call it again before the user has checked."
        )
    if action.status == DECLINED:
        return f"The user declined {name}. It did not run."
    if action.status == EXPIRED:
        if action.error_code:
            # It was approved, failed, and was not approved again.
            return f"The user approved {name}, but it failed: {action.result or action.error_code}"
        return f"The user did not approve {name} before the conversation moved on. It did not run."
    return None


def tool_title(connector: Connector | None, tool: str) -> str | None:
    """The tool's title from the connector's stored list, if it has one."""
    if connector is None:
        return None
    return next((t.get("title") for t in connector.tools if t["name"] == tool), None)


async def action_titles(session: AsyncSession, actions: list[ToolAction]) -> list[str | None]:
    """Each action's tool title, in order, for the cards."""
    ids = {action.connector_id for action in actions if action.connector_id is not None}
    connectors = (
        {
            row.id: row
            for row in (await session.execute(select(Connector).where(Connector.id.in_(ids))))
            .scalars()
            .all()
        }
        if ids
        else {}
    )
    return [
        tool_title(connectors.get(action.connector_id) if action.connector_id else None, action.tool)
        for action in actions
    ]
