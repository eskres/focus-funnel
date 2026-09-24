"""Deleting a user's content, their usage history, or the user and everything they own."""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, SearchIndex, Thought, UsageEvent, User


async def delete_user_data(session: AsyncSession, user: User) -> None:
    """Delete the user and every row that cascades from it, and commit.

    Every user-owned table references users.id with ON DELETE CASCADE, so one
    delete removes conversations, messages, usage, provider keys, settings,
    thoughts, and their search indexes.
    """
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()


async def delete_user_content(session: AsyncSession, user: User) -> None:
    """Delete the user's thoughts, search indexes, and conversations, in one transaction.

    Search entries cascade from thoughts and indexes, and messages from
    conversations. Usage records stay, with their conversation link cleared.
    The account, provider keys, and model settings stay too.
    """
    await session.execute(delete(Thought).where(Thought.user_id == user.id))
    await session.execute(delete(SearchIndex).where(SearchIndex.user_id == user.id))
    await session.execute(delete(Conversation).where(Conversation.user_id == user.id))
    await session.commit()


async def delete_user_usage(session: AsyncSession, user: User) -> None:
    """Delete the user's usage records, and nothing else."""
    await session.execute(delete(UsageEvent).where(UsageEvent.user_id == user.id))
    await session.commit()
