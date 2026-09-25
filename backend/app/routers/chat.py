"""POST /api/chat: one message in, an event stream of the answer out."""

import uuid

import httpx2
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import get_current_user
from app.chat.commands import parse_message
from app.chat.compaction import (
    compaction_request,
    draft_events,
    nothing_to_compact,
    plan_compaction,
)
from app.chat.config import ChatConfig, get_chat_config
from app.chat.context import check_room, fits
from app.chat.conversations import (
    claim_turn,
    get_conversation,
    list_messages,
    new_conversation,
    now,
    release_turn,
    switch_model,
    use_model,
)
from app.chat.loadout import find_loadout_model, get_default_model, get_loadout, temperature_for
from app.chat.model_call import open_model_call
from app.chat.model_info import model_info
from app.chat.prompt import PROPOSE_TOOL, SEARCH_TOOL, build_context, estimate_tokens, forced_tool
from app.chat.proposal import filing_for, held_parts, held_proposal
from app.chat.sse import sse_response
from app.chat.turn import Turn
from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.errors import ApiError, ErrorCode, context_full, model_not_set
from app.models import Conversation, Message, User
from app.providers import get_provider_http_client, provider_for_user

router = APIRouter(prefix="/api/chat")

CONVERSATION_HEADER = "X-Conversation-Id"

FORCED_TOOLS = {"push": PROPOSE_TOOL, "pull": SEARCH_TOOL}


class ModelRef(BaseModel):
    provider_id: str = Field(min_length=1)
    model: str = Field(min_length=1)


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str
    # The model and effort chosen in the composer, applied from this message on.
    provider_id: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    reasoning_effort: str | None = None
    # For /compact only: the loadout model the user chose to write this one
    # summary, when the conversation does not fit its own model.
    compact_model: ModelRef | None = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """The stream outlives the request's dependencies, so the chat opens its own session."""
    return get_sessionmaker()


async def _store_user_message(session: AsyncSession, conversation: Conversation, text: str) -> None:
    """Store the message, unless it resends the last one that got no answer."""
    messages = await list_messages(session, conversation)
    last = messages[-1] if messages else None
    if last is not None and last.role == "user" and last.content == text:
        return
    session.add(
        Message(
            conversation_id=conversation.id,
            position=(last.position + 1) if last is not None else 0,
            role="user",
            content=text,
        )
    )


async def _apply_choice(
    session: AsyncSession,
    user: User,
    conversation: Conversation,
    body: ChatRequest,
    config: ChatConfig,
) -> None:
    """Switch the conversation to the model chosen in the composer, if any."""
    if body.model is None and body.provider_id is None:
        return
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
        "reasoning_effort" in body.model_fields_set,
        config,
    )


async def _ensure_model(session: AsyncSession, user: User, conversation: Conversation) -> None:
    """A conversation with no model takes the default, or the call is refused."""
    if conversation.model is None:
        default = await get_default_model(session, user)
        if default is None:
            raise model_not_set()
        use_model(conversation, default)
        await session.commit()


@router.post("")
async def chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    config: ChatConfig = Depends(get_chat_config),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> StreamingResponse:
    """Answer a message as an event stream.

    Everything that can fail before the first byte happens here, so those
    failures are ordinary error responses. Once the conversation is stored,
    an error response carries its id in the X-Conversation-Id header.
    """
    parsed = parse_message(body.message)
    if parsed.command == "delete":
        raise ApiError(
            422, ErrorCode.VALIDATION_ERROR, "/delete is done in the chat screen, after you confirm."
        )
    if parsed.command == "compact":
        return await compact(body, user, session_factory(), config, settings, http_client)

    session = session_factory()
    conversation_id: uuid.UUID | None = None
    claimed = False
    try:
        if body.conversation_id is not None:
            conversation = await get_conversation(session, user, body.conversation_id)
            is_new = False
        else:
            conversation = new_conversation(user, body.message, await get_default_model(session, user))
            is_new = True
        conversation_id = conversation.id

        await _apply_choice(session, user, conversation, body, config)

        if is_new:
            conversation.turn_started_at = now()
            session.add(conversation)
            await session.flush()
        else:
            await claim_turn(session, conversation)
        claimed = True

        conversation.archived_at = None
        conversation.last_activity_at = now()
        await _store_user_message(session, conversation, body.message)
        await session.commit()

        await _ensure_model(session, user, conversation)

        held = held_parts(await held_proposal(session, conversation))
        context = build_context(await list_messages(session, conversation), held)
        filing = await filing_for(session, user, config)
        info = await model_info(
            session, user, conversation.provider_id, conversation.model, settings, http_client
        )
        check_room(
            conversation, context, body.message, info.context_length if info else None, config
        )

        provider = await provider_for_user(session, user, conversation.provider_id, settings)
        call = await open_model_call(
            session,
            user,
            provider,
            conversation.model,
            temperature=await temperature_for(session, user, config),
            max_tokens=config.reply_max_tokens,
            reasoning_effort=conversation.reasoning_effort,
            settings=settings,
            http_client=http_client,
        )
        turn = Turn(
            session,
            user,
            conversation,
            call,
            config,
            context=context,
            filing=filing,
            forced_tool=forced_tool(FORCED_TOOLS[parsed.command])
            if parsed.command in FORCED_TOOLS
            else None,
            command=parsed.command,
            held_parts=held,
            settings=settings,
            http_client=http_client,
        )
        try:
            await turn.open()
        except BaseException:
            await call.aclose()
            raise
    except BaseException as exc:
        await session.rollback()
        if claimed:
            await release_turn(session, conversation_id)
        await session.close()
        if isinstance(exc, ApiError) and claimed:
            exc.headers[CONVERSATION_HEADER] = str(conversation_id)
        raise

    async def events():
        if is_new:
            yield ("conversation", {"id": str(conversation_id), "title": conversation.title})
        async for event in turn.events():
            yield event

    async def on_close() -> None:
        try:
            await call.aclose()
            await session.commit()
            await release_turn(session, conversation_id)
        finally:
            await session.close()

    return sse_response(events(), on_close=on_close)


async def larger_models(
    session: AsyncSession,
    user: User,
    needed_tokens: int,
    config: ChatConfig,
    settings: Settings,
    http_client: httpx2.AsyncClient | None,
) -> list[dict]:
    """The loadout models whose context is known to hold the summary call."""
    choices = []
    for row in await get_loadout(session, user):
        info = await model_info(session, user, row.provider_id, row.model, settings, http_client)
        if info is not None and info.context_length and fits(
            needed_tokens, info.context_length, config
        ):
            choices.append(
                {
                    "provider_id": row.provider_id,
                    "model": row.model,
                    "context_length": info.context_length,
                }
            )
    return choices


async def compact(
    body: ChatRequest,
    user: User,
    session: AsyncSession,
    config: ChatConfig,
    settings: Settings,
    http_client: httpx2.AsyncClient | None,
) -> StreamingResponse:
    """/compact: stream a summary draft of all but the recent messages.

    Nothing in the conversation changes: the user accepts the draft through
    the compaction endpoint. When the summary call does not fit the
    conversation's model, the stream lists the loadout models that fit and
    no model is called until the user chooses one.
    """
    if body.conversation_id is None:
        raise ApiError(
            422, ErrorCode.VALIDATION_ERROR, "/compact works in a conversation that has messages."
        )
    claimed = False
    call = None
    try:
        conversation = await get_conversation(session, user, body.conversation_id)
        await _apply_choice(session, user, conversation, body, config)
        await claim_turn(session, conversation)
        claimed = True
        await _ensure_model(session, user, conversation)

        plan = plan_compaction(await list_messages(session, conversation), config.compact_keep_recent)
        if not plan.replaced:
            raise nothing_to_compact(config.compact_keep_recent)
        request = compaction_request(plan)
        needed = estimate_tokens(request)

        provider_id, model, effort = (
            conversation.provider_id,
            conversation.model,
            conversation.reasoning_effort,
        )
        if body.compact_model is not None:
            row = await find_loadout_model(
                session, user, body.compact_model.provider_id, body.compact_model.model
            )
            if row is None:
                raise ApiError(
                    422,
                    ErrorCode.VALIDATION_ERROR,
                    f"The model '{body.compact_model.model}' is not in your loadout.",
                )
            provider_id, model, effort = row.provider_id, row.model, row.reasoning_effort
        info = await model_info(session, user, provider_id, model, settings, http_client)
        if not fits(needed, info.context_length if info else None, config):
            if body.compact_model is not None:
                raise context_full()
            choices = await larger_models(session, user, needed, config, settings, http_client)
            payload = {
                "needed_tokens": needed,
                "context_length": info.context_length if info else None,
                "models": choices,
            }

            async def choose():
                yield ("compact_models", payload)

            return sse_response(choose(), on_close=_closer(session, conversation.id, None))

        provider = await provider_for_user(session, user, provider_id, settings)
        call = await open_model_call(
            session,
            user,
            provider,
            model,
            temperature=await temperature_for(session, user, config),
            max_tokens=config.reply_max_tokens,
            reasoning_effort=effort,
            settings=settings,
            http_client=http_client,
        )
        chunks = await call.stream(request)
    except BaseException:
        if call is not None:
            await call.aclose()
        await session.rollback()
        if claimed:
            await release_turn(session, body.conversation_id)
        await session.close()
        raise

    return sse_response(
        draft_events(session, call, chunks, plan, conversation),
        on_close=_closer(session, conversation.id, call),
    )


def _closer(session: AsyncSession, conversation_id: uuid.UUID, call):
    async def on_close() -> None:
        try:
            if call is not None:
                await call.aclose()
            await session.rollback()
            await release_turn(session, conversation_id)
        finally:
            await session.close()

    return on_close
