"""The user's stored conversations: list, read, change, and delete."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.chat.config import ChatConfig, get_chat_config
from app.chat.conversations import get_conversation, list_messages, now, switch_model
from app.db import get_session
from app.errors import ApiError, ErrorCode
from app.models import Conversation, Message, User

router = APIRouter(prefix="/api/conversations")


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    provider_id: str | None
    model: str | None
    reasoning_effort: str | None
    archived: bool
    last_activity_at: datetime
    created_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    position: int
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None
    status: str
    error_code: str | None
    compacted: bool
    created_at: datetime


class ConversationDetail(ConversationSummary):
    last_prompt_tokens: int | None
    held_proposal: dict[str, Any] | None
    messages: list[MessageOut]


class ConversationList(BaseModel):
    conversations: list[ConversationSummary]
    archived: list[ConversationSummary]


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None
    provider_id: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    reasoning_effort: str | None = None


def summary(conversation: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        provider_id=conversation.provider_id,
        model=conversation.model,
        reasoning_effort=conversation.reasoning_effort,
        archived=conversation.archived_at is not None,
        last_activity_at=conversation.last_activity_at,
        created_at=conversation.created_at,
    )


def detail(conversation: Conversation, messages: list[Message]) -> ConversationDetail:
    return ConversationDetail(
        **summary(conversation).model_dump(),
        last_prompt_tokens=conversation.last_prompt_tokens,
        held_proposal=conversation.held_proposal,
        messages=[
            MessageOut(
                id=m.id,
                position=m.position,
                role=m.role,
                content=m.content,
                tool_calls=m.tool_calls,
                tool_call_id=m.tool_call_id,
                status=m.status,
                error_code=m.error_code,
                compacted=m.compacted,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.get("", response_model=ConversationList)
async def list_conversations(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationList:
    rows = (
        await session.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.last_activity_at.desc(), Conversation.created_at.desc())
        )
    ).scalars()
    main, archived = [], []
    for row in rows:
        (archived if row.archived_at is not None else main).append(summary(row))
    return ConversationList(conversations=main, archived=archived)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def read_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationDetail:
    conversation = await get_conversation(session, user, conversation_id)
    return detail(conversation, await list_messages(session, conversation))


@router.patch("/{conversation_id}", response_model=ConversationDetail)
async def change_conversation(
    conversation_id: uuid.UUID,
    body: ConversationPatch,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    config: ChatConfig = Depends(get_chat_config),
) -> ConversationDetail:
    conversation = await get_conversation(session, user, conversation_id)
    given = body.model_fields_set
    if body.title is not None:
        title = " ".join(body.title.split())
        if not title:
            raise ApiError(422, ErrorCode.VALIDATION_ERROR, "A title must not be empty.")
        conversation.title = title
    if body.archived is not None:
        conversation.archived_at = now() if body.archived else None
    if body.model is not None or body.provider_id is not None:
        if body.model is None or body.provider_id is None:
            raise ApiError(
                422, ErrorCode.VALIDATION_ERROR, "Give both provider_id and model to switch model."
            )
        await switch_model(
            session,
            user,
            conversation,
            body.provider_id,
            body.model,
            body.reasoning_effort,
            "reasoning_effort" in given,
            config,
        )
    elif "reasoning_effort" in given:
        if conversation.model is None:
            raise ApiError(
                422, ErrorCode.VALIDATION_ERROR, "Choose a model before choosing an effort."
            )
        await switch_model(
            session,
            user,
            conversation,
            conversation.provider_id,
            conversation.model,
            body.reasoning_effort,
            True,
            config,
        )
    await session.commit()
    return detail(conversation, await list_messages(session, conversation))


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a conversation and its messages for good. Usage records stay."""
    conversation = await get_conversation(session, user, conversation_id)
    await session.execute(delete(Conversation).where(Conversation.id == conversation.id))
    await session.commit()
    return Response(status_code=204)
