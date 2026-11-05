"""Scope user-owned records to their owner.

A record owned by someone else is reported exactly like a record that does
not exist, so responses never reveal that another user's record exists.
"""

import uuid
from typing import Any, Protocol, TypeVar

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.models import User


class OwnedModel(Protocol):
    id: Any
    user_id: Any


T = TypeVar("T", bound=OwnedModel)


def not_found() -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND, "Not found.")


def owned_by(model: type[OwnedModel], user: User) -> ColumnElement[bool]:
    """Filter for list queries: select(Model).where(owned_by(Model, user))."""
    return model.user_id == user.id


async def get_owned_or_404(
    session: AsyncSession,
    model: type[T],
    record_id: uuid.UUID,
    user: User,
    *where: ColumnElement[bool],
) -> T:
    """The user's record with this id, or 404.

    Extra conditions narrow it further, such as an action's conversation
    (ToolAction.conversation_id == conversation_id); a record that fails one
    is reported as missing too.
    """
    record = (
        await session.execute(
            select(model).where(model.id == record_id, owned_by(model, user), *where)
        )
    ).scalar_one_or_none()
    if record is None:
        raise not_found()
    return record
