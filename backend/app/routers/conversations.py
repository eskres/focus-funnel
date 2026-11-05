"""The user's stored conversations: list, read, change, and delete."""

import uuid
from datetime import datetime
from typing import Any

import httpx2
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.chat.actions import action_payload, action_titles, list_actions
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
    filing_for,
    held_parts,
    held_proposal,
    list_proposals,
    offer_proposal,
    proposal_payload,
)
from app.chat.tool_providers import (
    ConnectorTools,
    connector_definitions,
    connector_tool_count,
    connector_tools,
    conversation_connector_tools,
)
from app.config import Settings, get_settings
from app.connector_config import get_connector_config
from app.db import get_session
from app.errors import ApiError, ErrorCode, too_many_tools
from app.mcp_client import get_mcp_connect
from app.models import Conversation, ConversationConnector, Proposal, User
from app.ownership import not_found
from app.providers import get_provider_http_client
from app.routers.actions import ActionOut
from app.routers.connectors import get_visible
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
    # The estimated tokens of the tool definitions offered, built-in and from
    # connectors (openspec mcp-connectors design decision 10).
    tool_tokens: int = 0


class ConversationConnectorOut(BaseModel):
    id: uuid.UUID
    name: str


class ConversationDetail(ConversationSummary):
    last_prompt_tokens: int | None
    held_proposal_id: uuid.UUID | None
    context: ContextMeter
    messages: list[MessageOut]
    proposals: list[ProposalOut]
    # Connector actions, for their cards (always empty while MCP_ENABLED is off).
    actions: list[ActionOut] = []
    # The connectors that are on, by name (always empty while MCP_ENABLED is off).
    connectors: list[ConversationConnectorOut] = []


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


class ConnectorsIn(BaseModel):
    # The connectors to have on: the whole set, not a change.
    connector_ids: list[uuid.UUID]


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
    config: ChatConfig,
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
    actions = await list_actions(session, conversation.id) if settings.mcp_enabled else []
    # The connectors the next turn would offer. Nothing is read while
    # MCP_ENABLED is off, and nothing here connects to a server.
    connectors = await conversation_connector_tools(
        session, user.id, conversation.id, settings, get_mcp_connect(), config.connectors
    )
    filing = await filing_for(session, user, config)
    gauge = meter(
        conversation,
        build_context(messages, held, connectors=bool(connectors), actions=actions),
        info.context_length if info is not None else None,
        tools=[*filing.tools, *connector_definitions(connectors)],
    )
    return ConversationDetail(
        **summary(conversation).model_dump(),
        last_prompt_tokens=conversation.last_prompt_tokens,
        held_proposal_id=conversation.held_proposal_id,
        context=ContextMeter(
            tokens=gauge.tokens,
            estimated=gauge.estimated,
            context_length=gauge.context_length,
            tool_tokens=gauge.tool_tokens,
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
        actions=[
            ActionOut(**action_payload(a, title))
            for a, title in zip(actions, await action_titles(session, actions), strict=True)
        ],
        connectors=[ConversationConnectorOut(id=c.connector_id, name=c.name) for c in connectors],
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
    config: ChatConfig = Depends(get_chat_config),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ConversationDetail:
    conversation = await get_conversation(session, user, conversation_id)
    return await detail(session, user, conversation, config, settings, http_client)


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
    return await detail(session, user, conversation, config, settings, http_client)


@router.put("/{conversation_id}/connectors", response_model=ConversationDetail)
async def set_connectors(
    conversation_id: uuid.UUID,
    body: ConnectorsIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    config: ChatConfig = Depends(get_chat_config),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ConversationDetail:
    """Set which connectors are on in the conversation, from the next turn.

    The body names the whole set. Turning on a connector with no tools
    switched on is refused, and so is any turn-on that takes the
    conversation past connectors.max_tools; turning connectors off always
    works. A change clears the reported prompt count, so the meter shows an
    estimate until the next answer (openspec mcp-connectors decision 10).
    Links to connectors that cannot be offered now (an operator entry that
    is gone, or a user connector while users may not have their own) are
    left alone.
    """
    if not settings.mcp_enabled:
        raise not_found()
    conversation = await get_conversation(session, user, conversation_id)
    connector_config = get_connector_config()
    connect = get_mcp_connect()
    wanted: dict[uuid.UUID, ConnectorTools] = {}
    for connector_id in dict.fromkeys(body.connector_ids):
        connector = await get_visible(session, connector_id, user, connector_config, settings)
        provider = connector_tools(connector, settings, connect, config.connectors)
        if provider is None:
            raise not_found()
        wanted[connector.id] = provider

    linked = set(
        (
            await session.execute(
                select(ConversationConnector.connector_id).where(
                    ConversationConnector.conversation_id == conversation.id
                )
            )
        ).scalars()
    )
    offered = {
        provider.connector_id
        for provider in await conversation_connector_tools(
            session, user.id, conversation.id, settings, connect, config.connectors
        )
    }
    added = [connector_id for connector_id in wanted if connector_id not in linked]
    removed = offered - set(wanted)
    for connector_id in added:
        if not wanted[connector_id].definitions():
            raise ApiError(
                422,
                ErrorCode.VALIDATION_ERROR,
                f"connector_ids: {wanted[connector_id].name} has no tools switched on. "
                "Switch some on in settings first.",
            )
    if added and connector_tool_count(list(wanted.values())) > config.connectors.max_tools:
        raise too_many_tools(config.connectors.max_tools)

    if added or removed:
        if removed:
            await session.execute(
                delete(ConversationConnector).where(
                    ConversationConnector.conversation_id == conversation.id,
                    ConversationConnector.connector_id.in_(removed),
                )
            )
        session.add_all(
            ConversationConnector(conversation_id=conversation.id, connector_id=connector_id)
            for connector_id in added
        )
        # The offered tools changed, so the last reported count no longer holds.
        conversation.last_prompt_tokens = None
        try:
            await session.commit()
        except IntegrityError:
            # Another request turned the same connector on at the same time.
            await session.rollback()
            raise ApiError(
                409,
                ErrorCode.CONVERSATION_BUSY,
                "The connectors were changed in another tab at the same time. Try again.",
            ) from None
    return await detail(session, user, conversation, config, settings, http_client)


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
    return await detail(session, user, conversation, config, settings, http_client)


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
