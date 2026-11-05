"""POST /api/conversations/{id}/actions/{action_id}: approve or decline a card.

Openspec mcp-connectors design decisions 7 and 19. An action moves from
pending (or failed) to running, declined, or expired with one conditional
update, so two approvals from two tabs run the tool once: the one that loses
waits for the outcome and answers the same. Answers 404 not_found while
MCP_ENABLED is off, like the connector routes.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import anyio
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.chat.actions import (
    DECLINED,
    DONE,
    EXPIRED,
    FAILED,
    RUNNING,
    TOOL_ERROR,
    action_payload,
    move,
    moved_on,
    tool_title,
)
from app.chat.config import ChatConfig, ConnectorLimits, get_chat_config
from app.chat.conversations import TURN_CLAIM_TIMEOUT, get_conversation
from app.chat.tool_providers import ConnectorTools, connector_tools
from app.config import Settings, get_settings
from app.connectors import full_name
from app.db import get_session
from app.errors import ErrorCode, action_expired, action_running, conversation_busy
from app.mcp_client import McpConnect, get_mcp_connect, result_text
from app.models import Connector, Conversation, ConversationConnector, ToolAction, User
from app.ownership import get_owned_or_404
from app.routers.connectors import require_mcp_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", dependencies=[Depends(require_mcp_enabled)])

# How often a request that found the action running looks again.
POLL_SECONDS = 0.1


class DecisionIn(BaseModel):
    decision: Literal["approve", "decline"]


class ActionOut(BaseModel):
    id: uuid.UUID
    # The position of the tool message the card belongs after.
    position: int
    # Null once the connector is removed; the card keeps its name.
    connector_id: uuid.UUID | None
    connector: str
    # The server's tool name, without the connector prefix.
    tool: str
    title: str | None
    arguments: dict[str, Any]
    # pending, running, done, failed, declined, or expired.
    status: str
    # done: what the server returned (capped, without the data marking);
    # failed: why it did not run ("The server could not be reached.").
    result: str | None
    # failed: the connector failure code; done: tool_error when the server
    # reported an error.
    error_code: str | None


async def _turn_running(session: AsyncSession, conversation_id: uuid.UUID) -> bool:
    started_after = datetime.now(UTC) - TURN_CLAIM_TIMEOUT
    return bool(
        (
            await session.execute(
                select(
                    exists().where(
                        Conversation.id == conversation_id,
                        Conversation.turn_started_at.is_not(None),
                        Conversation.turn_started_at >= started_after,
                    )
                )
            )
        ).scalar_one()
    )


async def _connector(session: AsyncSession, action: ToolAction, user: User) -> Connector | None:
    if action.connector_id is None:
        return None
    return (
        await session.execute(
            select(Connector).where(Connector.id == action.connector_id, Connector.user_id == user.id)
        )
    ).scalar_one_or_none()


async def _provider(
    session: AsyncSession,
    action: ToolAction,
    connector: Connector | None,
    settings: Settings,
    connect: McpConnect,
    limits: ConnectorLimits,
) -> ConnectorTools | None:
    """The connector's tools when the action's tool may still run: the
    connector exists, is on in the conversation, may be offered, and the
    tool is still available and switched on. None otherwise."""
    if connector is None:
        return None
    linked = (
        await session.execute(
            select(
                exists().where(
                    ConversationConnector.conversation_id == action.conversation_id,
                    ConversationConnector.connector_id == connector.id,
                )
            )
        )
    ).scalar_one()
    if not linked:
        return None
    provider = connector_tools(connector, settings, connect, limits)
    if provider is None or not provider.owns(full_name(connector.name, action.tool)):
        return None
    return provider


async def _run(
    session: AsyncSession, action: ToolAction, provider: ConnectorTools, limits: ConnectorLimits
) -> None:
    """Call the server for a running action and store done or failed."""
    try:
        try:
            run = await provider.run(full_name(provider.name, action.tool), action.arguments)
        finally:
            await provider.aclose()
    except BaseException:
        # Cancelled (the request went away): the action did not finish, so
        # it may be approved again rather than staying running.
        with anyio.CancelScope(shield=True):
            action.status, action.result = FAILED, "The approval was interrupted."
            action.error_code = ErrorCode.INTERNAL_ERROR
            await session.commit()
        raise
    if run.result is not None:
        action.status = DONE
        action.result = result_text(run.result, limits.result_max_chars)
        action.error_code = TOOL_ERROR if run.result.is_error else None
    else:
        action.status = FAILED
        action.result = f"The server {run.reason}."
        action.error_code = run.code
    await session.commit()


@router.post("/{conversation_id}/actions/{action_id}", response_model=ActionOut)
async def decide_action(
    conversation_id: uuid.UUID,
    action_id: uuid.UUID,
    body: DecisionIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    config: ChatConfig = Depends(get_chat_config),
    settings: Settings = Depends(get_settings),
    connect: McpConnect = Depends(get_mcp_connect),
) -> ActionOut:
    """Approve or decline an action (decision 7).

    done or declined answers the stored outcome, so a repeated approval is a
    no-op; expired answers 409 action_expired. A request that finds the
    action running waits for its outcome, up to the connector's time limits,
    and then answers 409 action_running. A pending or failed action is
    refused with conversation_busy while a turn runs, and expires when the
    conversation moved on or its tool may no longer run.
    """
    limits = config.connectors
    conversation = await get_conversation(session, user, conversation_id)
    action = await get_owned_or_404(
        session, ToolAction, action_id, user, ToolAction.conversation_id == conversation.id
    )
    connector = await _connector(session, action, user)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limits.connect_seconds + limits.call_seconds + 1
    while True:
        if action.status in (DONE, DECLINED):
            break
        if action.status == EXPIRED:
            raise action_expired()
        if action.status == RUNNING:
            if loop.time() > deadline:
                raise action_running()
            # End the read transaction (without expiring the loaded rows),
            # so the next read sees the winner's commit.
            await session.commit()
            await asyncio.sleep(POLL_SECONDS)
            await session.refresh(action)
            continue

        # Pending or failed.
        if await _turn_running(session, conversation.id):
            raise conversation_busy()
        if await moved_on(session, action):
            # The loop then answers action_expired, or whatever a racing
            # request stored first.
            await move(session, action, EXPIRED)
            continue
        if body.decision == "decline":
            await move(session, action, DECLINED)
            continue
        provider = await _provider(session, action, connector, settings, connect, limits)
        if provider is None:
            await move(session, action, EXPIRED)
            continue
        if not await move(session, action, RUNNING):
            continue
        await _run(session, action, provider, limits)
        break
    connector = await _connector(session, action, user)
    return ActionOut(**action_payload(action, tool_title(connector, action.tool)))
