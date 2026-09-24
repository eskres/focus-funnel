"""Deleting a user and everything they own."""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def delete_user_data(session: AsyncSession, user: User) -> None:
    """Delete the user and every row that cascades from it, and commit.

    Every user-owned table references users.id with ON DELETE CASCADE, so one
    delete removes conversations, messages, usage, provider keys, settings,
    thoughts, and their search indexes.
    """
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
