"""POST /api/chat: one message in, an event stream of the answer out."""

import uuid

import httpx2
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import get_current_user
from app.chat.commands import parse_message
from app.chat.config import ChatConfig, get_chat_config
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
from app.chat.loadout import get_default_model, temperature_for
from app.chat.model_call import open_model_call
from app.chat.prompt import PROPOSE_TOOL, SEARCH_TOOL, build_context, forced_tool
from app.chat.sse import sse_response
from app.chat.turn import Turn
from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.errors import ApiError, ErrorCode, model_not_set
from app.models import Conversation, Message, User
from app.providers import get_provider_http_client, provider_for_user

router = APIRouter(prefix="/api/chat")

CONVERSATION_HEADER = "X-Conversation-Id"

FORCED_TOOLS = {"push": PROPOSE_TOOL, "pull": SEARCH_TOOL}


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str
    # The model and effort chosen in the composer, applied from this message on.
    provider_id: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    reasoning_effort: str | None = None


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
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "/compact is not available yet.")

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
                "reasoning_effort" in body.model_fields_set,
                config,
            )

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

        if conversation.model is None:
            default = await get_default_model(session, user)
            if default is None:
                raise model_not_set()
            use_model(conversation, default)
            await session.commit()

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
            context=build_context(await list_messages(session, conversation)),
            forced_tool=forced_tool(FORCED_TOOLS[parsed.command])
            if parsed.command in FORCED_TOOLS
            else None,
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
