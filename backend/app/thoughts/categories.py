"""Thought categories: five fixed kinds for everyone, and the ones a user adds."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.models import User, UserCategory

FIXED_CATEGORIES = ("task", "idea", "decision", "note", "reference")
MAX_ADDED = 20
MAX_NAME = 30


def clean_name(name: str) -> str:
    """A category name as it is stored: trimmed, lowercased, inner spaces collapsed."""
    return " ".join(name.split()).lower()


def check_name(name: str) -> str:
    cleaned = clean_name(name)
    if not cleaned:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "name: must not be empty")
    if len(cleaned) > MAX_NAME:
        raise ApiError(
            422, ErrorCode.VALIDATION_ERROR, f"name: must be at most {MAX_NAME} characters"
        )
    return cleaned


async def added_categories(session: AsyncSession, user: User) -> list[str]:
    """The user's added categories, oldest first."""
    rows = await session.execute(
        select(UserCategory.name)
        .where(UserCategory.user_id == user.id)
        .order_by(UserCategory.created_at, UserCategory.name)
    )
    return list(rows.scalars())


async def user_categories(session: AsyncSession, user: User) -> list[str]:
    """Every category the user can pick: the fixed kinds, then the added ones."""
    return [*FIXED_CATEGORIES, *await added_categories(session, user)]


def category_exists(name: str) -> ApiError:
    return ApiError(409, ErrorCode.CATEGORY_EXISTS, f"The category '{name}' exists already.")


async def add_category(session: AsyncSession, user: User, name: str) -> str:
    cleaned = check_name(name)
    added = await added_categories(session, user)
    if cleaned in FIXED_CATEGORIES or cleaned in added:
        raise category_exists(cleaned)
    if len(added) >= MAX_ADDED:
        raise ApiError(
            422,
            ErrorCode.VALIDATION_ERROR,
            f"name: you can add at most {MAX_ADDED} categories. Remove one first.",
        )
    session.add(UserCategory(user_id=user.id, name=cleaned))
    await session.commit()
    return cleaned


async def remove_category(session: AsyncSession, user: User, name: str) -> None:
    """Remove an added category. Thoughts that have it keep it."""
    cleaned = clean_name(name)
    if cleaned in FIXED_CATEGORIES:
        raise ApiError(
            422, ErrorCode.VALIDATION_ERROR, f"name: '{cleaned}' is a fixed kind and stays."
        )
    row = (
        await session.execute(
            select(UserCategory).where(UserCategory.user_id == user.id, UserCategory.name == cleaned)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Not found.")
    await session.delete(row)
    await session.commit()
