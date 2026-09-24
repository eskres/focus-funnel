"""The user's stored conversations: list, read, change, and delete."""

import uuid
from datetime import datetime
from typing import Any

import httpx2
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.chat.compaction import store_compaction
from app.chat.config import ChatConfig, get_chat_config
from app.chat.context import meter
from app.chat import tools
from app.chat.conversations import (
    claim_turn,
    get_conversation,
    list_messages,
    now,
    release_turn,
    switch_model,
)
from app.chat.model_info import model_info
from app.chat.prompt import build_context
from app.chat.proposal import offer_proposal
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError, ErrorCode
from app.models import Conversation, User
from app.providers import get_provider_http_client

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


class ContextMeter(BaseModel):
    """How full the context is: the tokens in use against the model's context length."""

    tokens: int
    # True until the next answer reports the model's own count.
    estimated: bool
    context_length: int | None


class ConversationDetail(ConversationSummary):
    last_prompt_tokens: int | None
    held_proposal: dict[str, Any] | None
    context: ContextMeter
    messages: list[MessageOut]


class CompactionIn(BaseModel):
    summary: str = Field(min_length=1)
    # The last message the summary replaces, from the compact_draft event.
    through_position: int = Field(ge=0)


class ConversationList(BaseModel):
    conversations: list[ConversationSummary]
    archived: list[ConversationSummary]


class ProposalIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list, max_length=20)


class ConfirmOutcome(BaseModel):
    saved: bool
    message: str
    proposal: ProposalIn


class OfferedProposal(BaseModel):
    held_proposal: dict[str, Any] | None


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


async def detail(
    session: AsyncSession,
    user: User,
    conversation: Conversation,
    settings: Settings,
    http_client: httpx2.AsyncClient | None,
) -> ConversationDetail:
    messages = await list_messages(session, conversation)
    info = (
        await model_info(
            session, user, conversation.provider_id, conversation.model, settings, http_client
        )
        if conversation.model is not None
        else None
    )
    gauge = meter(
        conversation,
        build_context(messages, conversation.held_proposal),
        info.context_length if info is not None else None,
    )
    return ConversationDetail(
        **summary(conversation).model_dump(),
        last_prompt_tokens=conversation.last_prompt_tokens,
        held_proposal=conversation.held_proposal,
        context=ContextMeter(
            tokens=gauge.tokens, estimated=gauge.estimated, context_length=gauge.context_length
        ),
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
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ConversationDetail:
    conversation = await get_conversation(session, user, conversation_id)
    return await detail(session, user, conversation, settings, http_client)


@router.patch("/{conversation_id}", response_model=ConversationDetail)
async def change_conversation(
    conversation_id: uuid.UUID,
    body: ConversationPatch,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    config: ChatConfig = Depends(get_chat_config),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
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
    return await detail(session, user, conversation, settings, http_client)


@router.post("/{conversation_id}/compaction", response_model=ConversationDetail)
async def accept_compaction(
    conversation_id: uuid.UUID,
    body: CompactionIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    config: ChatConfig = Depends(get_chat_config),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ConversationDetail:
    """Store the summary the user accepted, as they edited it.

    The messages up to through_position, and any earlier summary, are marked
    compacted: the transcript still shows them, and the model gets the
    summary instead.
    """
    conversation = await get_conversation(session, user, conversation_id)
    text = body.summary.strip()
    if not text:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "A summary must not be empty.")
    await claim_turn(session, conversation)
    try:
        await store_compaction(
            session,
            conversation,
            await list_messages(session, conversation),
            text,
            body.through_position,
            config,
        )
        await session.commit()
    finally:
        await session.rollback()
        await release_turn(session, conversation_id)
    await session.refresh(conversation)
    return await detail(session, user, conversation, settings, http_client)


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


@router.post("/{conversation_id}/proposal", response_model=OfferedProposal)
async def offer_held_proposal(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    config: ChatConfig = Depends(get_chat_config),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> OfferedProposal:
    """The proposal to show before archive or /compact.

    A held proposal comes back as it is. Without one, the model is asked for
    one (a forced call), and it is held from then on. None means there is
    nothing to propose, and the action goes ahead.
    """
    conversation = await get_conversation(session, user, conversation_id)
    if conversation.held_proposal is not None:
        return OfferedProposal(held_proposal=conversation.held_proposal)
    await claim_turn(session, conversation)
    try:
        held = await offer_proposal(session, user, conversation, config, settings, http_client)
    finally:
        await session.rollback()
        await release_turn(session, conversation_id)
    return OfferedProposal(held_proposal=held)


@router.post("/{conversation_id}/proposal/confirm", response_model=ConfirmOutcome)
async def confirm_proposal(
    conversation_id: uuid.UUID,
    body: ProposalIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConfirmOutcome:
    """Hand the proposal, as the user edited it, to thought storage.

    A saved proposal is no longer held. One that could not be saved stays
    held, and its text comes back so the card can keep it.
    """
    conversation = await get_conversation(session, user, conversation_id)
    title = body.title.strip()
    summary = body.summary.strip()
    if not title or not summary:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "A proposal needs a title and a summary.")
    proposal = tools.Proposal(
        title=title, summary=summary, tags=[tag.strip() for tag in body.tags if tag.strip()]
    )
    outcome = await tools.save_thought(user, proposal)
    if outcome.saved:
        conversation.held_proposal = None
        await session.commit()
    return ConfirmOutcome(
        saved=outcome.saved, message=outcome.message, proposal=ProposalIn(**proposal.as_dict())
    )
