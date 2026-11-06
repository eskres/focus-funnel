"""Deleting a user's content, their usage history, or the user and everything they own."""

import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import running
from app.chat.conversations import claim_user_turns
from app.models import Conversation, SearchIndex, Thought, UsageEvent, User


async def stop_and_claim(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Stop the user's running answers, then claim every conversation of the
    user in a new transaction, which the delete that follows commits
    (stop-and-spend-cap design decision 13). Raises turns_busy, having
    rolled back, when an answer still holds a claim: nothing is deleted.

    The request's read transaction ends first, so no connection waits idle
    in a transaction while the turns stop.
    """
    await session.commit()
    await running.stop_turns(user_id)
    await claim_user_turns(session, user_id)


async def delete_user_data(session: AsyncSession, user: User) -> None:
    """Delete the user and every row that cascades from it, and commit.

    Every user-owned table references users.id with ON DELETE CASCADE, so one
    delete removes conversations, messages, usage, provider keys, settings,
    thoughts, their search indexes, connectors, the conversations' connector
    links, and tool actions.
    """
    await delete_user_by_id(session, user.id)


async def delete_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> None:
    """`delete_user_data` for a user known only by id.

    The user's exports stop first, so none ends looking complete
    (thought-export design decision 15). Every caller has stopped the user's
    answers and claimed their conversations before this, so a delete
    refused with 409 stops no export.
    """
    # Imported here: app.demo imports this module, and the export reads app.demo's clock.
    from app.thoughts.export import stop_exports

    stop_exports(user_id)
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()


async def delete_user_content(session: AsyncSession, user: User) -> None:
    """Delete the user's thoughts, search indexes, and conversations, in one transaction.

    Search entries cascade from thoughts and indexes, and messages,
    proposals, connector links, and tool actions from conversations. Usage
    records stay, with their conversation link cleared. The account, provider
    keys, model settings, added categories, and connectors stay too: they are
    settings.

    The user's exports stop first, after the caller's stop and claim
    (thought-export design decision 15).
    """
    # Imported here: app.demo imports this module, and the export reads app.demo's clock.
    from app.thoughts.export import stop_exports

    stop_exports(user.id)
    await session.execute(delete(Thought).where(Thought.user_id == user.id))
    await session.execute(delete(SearchIndex).where(SearchIndex.user_id == user.id))
    await session.execute(delete(Conversation).where(Conversation.user_id == user.id))
    await session.commit()


async def delete_user_usage(session: AsyncSession, user: User) -> None:
    """Delete the user's usage records, and nothing else."""
    await session.execute(delete(UsageEvent).where(UsageEvent.user_id == user.id))
    await session.commit()
