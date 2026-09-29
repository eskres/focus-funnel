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
from app.chat.proposal import (
    held_parts,
    held_proposal,
    list_proposals,
    offer_proposal,
    proposal_payload,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError, ErrorCode
from app.models import Conversation, Proposal, User
from app.providers import get_provider_http_client
from app.thoughts.categories import clean_name, user_categories
from app.thoughts.store import add_thought

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
    # {"proposal_id"} on a propose_thought result, {"sources"} on a search.
    details: dict[str, Any] | None
    created_at: datetime


class ProposalPart(BaseModel):
    title: str
    summary: str
    tags: list[str]
    category: str | None
    # Set once the part is saved.
    thought_id: uuid.UUID | None


class ProposalOut(BaseModel):
    id: uuid.UUID
    # The position of the tool message the card belongs after.
    position: int
    parts: list[ProposalPart]
    # The later proposal that replaced this one while it was held.
    replaced_by: uuid.UUID | None


class ContextMeter(BaseModel):
    """How full the context is: the tokens in use against the model's context length."""

    tokens: int
    # True until the next answer reports the model's own count.
    estimated: bool
    context_length: int | None


class ConversationDetail(ConversationSummary):
    last_prompt_tokens: int | None
    held_proposal_id: uuid.UUID | None
    context: ContextMeter
    messages: list[MessageOut]
    proposals: list[ProposalOut]


class CompactionIn(BaseModel):
    summary: str = Field(min_length=1)
    # The last message the summary replaces, from the compact_draft event.
    through_position: int = Field(ge=0)


class ConversationList(BaseModel):
    conversations: list[ConversationSummary]
    archived: list[ConversationSummary]


class ConfirmIn(BaseModel):
    # The indexes of the parts the card covers: one, or every part after a merge.
    parts: list[int] = Field(min_length=1)
    # The thought store checks the fields, so its messages name them.
    title: Any = None
    summary: Any = None
    tags: Any = None
    category: str | None = None


class ConfirmOutcome(BaseModel):
    saved: bool
    thought_id: uuid.UUID
    message: str


class OfferedProposal(BaseModel):
    proposal: ProposalOut | None


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
    held = held_parts(await held_proposal(session, conversation))
    gauge = meter(
        conversation,
        build_context(messages, held),
        info.context_length if info is not None else None,
    )
    return ConversationDetail(
        **summary(conversation).model_dump(),
        last_prompt_tokens=conversation.last_prompt_tokens,
        held_proposal_id=conversation.held_proposal_id,
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
                details=m.details,
                created_at=m.created_at,
            )
            for m in messages
        ],
        proposals=[
            ProposalOut(**proposal_payload(p)) for p in await list_proposals(session, conversation)
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

    A held proposal with a part not yet saved comes back as it is. Without
    one, the model is asked for one, which it may decline, and it is held from then
    on. None means there is nothing to propose, and the action goes ahead.
    """
    conversation = await get_conversation(session, user, conversation_id)
    held = await held_proposal(session, conversation)
    if held_parts(held) is not None:
        return OfferedProposal(proposal=ProposalOut(**proposal_payload(held)))
    await claim_turn(session, conversation)
    try:
        offered = await offer_proposal(session, user, conversation, config, settings, http_client)
        payload = proposal_payload(offered) if offered is not None else None
    finally:
        await session.rollback()
        await release_turn(session, conversation_id)
    return OfferedProposal(proposal=ProposalOut(**payload) if payload is not None else None)


def part_already_saved() -> ApiError:
    return ApiError(
        409,
        ErrorCode.PROPOSAL_PART_SAVED,
        "Part of this proposal was saved already, so it can no longer be merged. "
        "Save the other parts one by one.",
    )


@router.post(
    "/{conversation_id}/proposals/{proposal_id}/confirm", response_model=ConfirmOutcome
)
async def confirm_proposal(
    conversation_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: ConfirmIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ConfirmOutcome:
    """Save one card of a proposal, as the user edited it, with the proposal's raw text.

    The proposal row is locked, so a repeated or concurrent confirm of the
    same parts stores one thought and answers its id. The thought and the
    parts' thought_id are committed together.
    """
    conversation = await get_conversation(session, user, conversation_id)
    proposal = (
        await session.execute(
            select(Proposal)
            .where(Proposal.id == proposal_id, Proposal.conversation_id == conversation.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Not found.")

    indexes = sorted(set(body.parts))
    count = len(proposal.parts)
    if any(not 0 <= index < count for index in indexes):
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, f"parts: must be indexes from 0 to {count - 1}")
    if len(indexes) > 1 and len(indexes) != count:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "parts: name one part, or every part to merge them")

    saved = {proposal.parts[index].get("thought_id") for index in indexes}
    if len(saved) == 1 and None not in saved:
        return ConfirmOutcome(saved=True, thought_id=saved.pop(), message="Saved.")
    if any(saved - {None}):
        raise part_already_saved()

    category = clean_name(body.category) if body.category is not None else None
    if category == "":
        category = None
    if category is not None and category not in await user_categories(session, user):
        raise ApiError(
            422, ErrorCode.VALIDATION_ERROR, f"category: '{category}' is not one of your categories"
        )

    outcome = await add_thought(
        session,
        user,
        title=body.title,
        summary=body.summary,
        tags=body.tags,
        raw_text=proposal.raw_text,
        category=category,
        settings=settings,
        conversation_id=conversation.id,
        proposal_id=proposal.id,
        http_client=http_client,
    )
    thought_id = str(outcome.thought.id)
    # A new list, so the JSON column is written.
    proposal.parts = [
        {**part, "thought_id": thought_id} if index in indexes else part
        for index, part in enumerate(proposal.parts)
    ]
    if conversation.held_proposal_id == proposal.id and not any(
        part.get("thought_id") is None for part in proposal.parts
    ):
        conversation.held_proposal_id = None
    await session.commit()
    return ConfirmOutcome(saved=True, thought_id=outcome.thought.id, message="Saved.")
