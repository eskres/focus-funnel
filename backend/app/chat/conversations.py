"""Stored conversations: creating them, their model, and their messages."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ChatConfig
from app.chat.loadout import find_loadout_model
from app.errors import ApiError, ErrorCode, conversation_busy
from app.models import ChatModel, Conversation, Message, User
from app.ownership import get_owned_or_404

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
    conversation.turn_started_at = started


async def release_turn(session: AsyncSession, conversation_id: uuid.UUID) -> None:
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(turn_started_at=None)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
