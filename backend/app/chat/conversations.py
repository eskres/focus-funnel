"""Stored conversations: creating them, their model, and their messages."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.chat.config import ChatConfig
from app.chat.loadout import find_loadout_model
from app.errors import ApiError, ErrorCode, conversation_busy
from app.models import ChatModel, Conversation, Message, User
from app.ownership import get_owned_or_404

logger = logging.getLogger(__name__)

TITLE_LENGTH = 60


def now() -> datetime:
    return datetime.now(UTC)


def title_from(message: str) -> str:
    """The start of the first message, on one line, cut at a word where possible."""
    text = " ".join(message.split())
    if len(text) <= TITLE_LENGTH:
        return text
    cut = text[:TITLE_LENGTH]
    space = cut.rfind(" ")
    return (cut[:space] if space > TITLE_LENGTH // 2 else cut) + "…"


def use_model(conversation: Conversation, row: ChatModel) -> None:
    """Point the conversation at a loadout model, with that model's effort."""
    conversation.provider_id = row.provider_id
    conversation.model = row.model
    conversation.reasoning_effort = row.reasoning_effort


def new_conversation(user: User, message: str, default: ChatModel | None) -> Conversation:
    """A conversation for a first message, on the default model if one is set."""
    conversation = Conversation(
        id=uuid.uuid4(), user_id=user.id, title=title_from(message), last_activity_at=now()
    )
    if default is not None:
        use_model(conversation, default)
    return conversation


async def get_conversation(session: AsyncSession, user: User, conversation_id: uuid.UUID) -> Conversation:
    return await get_owned_or_404(session, Conversation, conversation_id, user)


async def switch_model(
    session: AsyncSession,
    user: User,
    conversation: Conversation,
    provider_id: str,
    model: str,
    effort: str | None,
    effort_given: bool,
    config: ChatConfig,
) -> None:
    """Change a conversation's model and effort from the next message on.

    The new model must be in the loadout, or be the conversation's own. The
    effort follows the new model's loadout effort unless one is given, and an
    effort the effort table says the model refuses is dropped. The stored
    prompt token count belongs to the old model, so it is cleared.
    """
    same_model = (provider_id, model) == (conversation.provider_id, conversation.model)
    row = await find_loadout_model(session, user, provider_id, model)
    if row is None and not same_model:
        raise ApiError(
            422, ErrorCode.VALIDATION_ERROR, f"The model '{model}' is not in your loadout."
        )
    if effort_given:
        if effort is not None and effort not in config.efforts_for(model):
            raise ApiError(
                422,
                ErrorCode.VALIDATION_ERROR,
                f"The model '{model}' does not accept reasoning effort '{effort}'.",
            )
    elif not same_model:
        effort = row.reasoning_effort if row is not None else None
    else:
        effort = conversation.reasoning_effort
    if effort is not None and effort not in config.efforts_for(model):
        effort = None

    if not same_model:
        conversation.last_prompt_tokens = None
    conversation.provider_id = provider_id
    conversation.model = model
    conversation.reasoning_effort = effort


async def list_messages(session: AsyncSession, conversation: Conversation) -> list[Message]:
    return list(
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.position)
            )
        ).scalars()
    )


async def next_position(session: AsyncSession, conversation: Conversation) -> int:
    highest = (
        await session.execute(
            select(func.max(Message.position)).where(Message.conversation_id == conversation.id)
        )
    ).scalar_one()
    return 0 if highest is None else highest + 1


# A turn that has not finished after this long is taken to have died with
# its server, so the conversation is free again.
TURN_CLAIM_TIMEOUT = timedelta(minutes=15)


async def claim_turn(session: AsyncSession, conversation: Conversation) -> None:
    """Mark a turn as running, or raise conversation_busy if one already is.

    One atomic update, so two requests cannot both win.
    """
    started = now()
    result = await session.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation.id,
            or_(
                Conversation.turn_started_at.is_(None),
                Conversation.turn_started_at < started - TURN_CLAIM_TIMEOUT,
            ),
        )
        .values(turn_started_at=started)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await session.rollback()
        raise conversation_busy()
    await session.commit()
    # Set as already stored: a plain assignment would make the next flush
    # write the claim again and hold that write open (a row lock, or SQLite's
    # database lock) until the session commits, which a /compact draft does
    # only when it ends.
    set_committed_value(conversation, "turn_started_at", started)


async def release_turn(session: AsyncSession, conversation_id: uuid.UUID) -> None:
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(turn_started_at=None)
        .execution_options(synchronize_session=False)
    )
    await session.commit()


async def last_message(session: AsyncSession, conversation_id: uuid.UUID) -> Message | None:
    return (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def ends_answered(last: Message | None) -> bool:
    """Whether a conversation whose last message is `last` needs no failed answer.

    An assistant message without tool calls is a stored answer (complete,
    cut, or failed). A summary is an accepted /compact, which answers no
    message. Anything else (the user's message, a tool call, a tool result)
    is a turn that stopped before its answer was stored.
    """
    if last is None or last.role == "summary":
        return True
    return last.role == "assistant" and not last.tool_calls


def chat_turn_claim(conversation: Conversation) -> bool:
    """Whether the conversation's claim was taken by a chat turn.

    A chat turn sets `last_activity_at` when it stores its message, after it
    claims. `/compact` and the proposal routes claim without touching it, so
    their claims started after the last activity.
    """
    started = conversation.turn_started_at
    return started is not None and conversation.last_activity_at >= started


def interrupted_answer(conversation_id: uuid.UUID, position: int, content: str | None = None) -> Message:
    """The failed answer stored for a turn the server stopped."""
    return Message(
        conversation_id=conversation_id,
        position=position,
        role="assistant",
        content=content or None,
        status="failed",
        error_code=ErrorCode.ANSWER_INTERRUPTED,
    )


async def release_stale_turns(session: AsyncSession) -> int:
    """Free every claimed conversation; run once at startup, before serving.

    The backend runs as one process, so a claim that exists when it starts
    belongs to a process that died mid-turn. A conversation whose chat turn
    stopped before its answer was stored gets a failed `answer_interrupted`
    answer, so it shows as not finished and can be sent again. Another claim
    (a `/compact` draft, a proposal being offered) answers no message, so it
    is only released. Returns how many claims were released.
    """
    claimed = list(
        (
            await session.execute(
                select(Conversation).where(Conversation.turn_started_at.is_not(None))
            )
        ).scalars()
    )
    for conversation in claimed:
        last = await last_message(session, conversation.id)
        if chat_turn_claim(conversation) and not ends_answered(last):
            session.add(interrupted_answer(conversation.id, last.position + 1))
        conversation.turn_started_at = None
    await session.commit()
    if claimed:
        logger.info("Released %d chat turn(s) a stopped server left claimed", len(claimed))
    return len(claimed)
