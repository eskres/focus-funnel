"""The categories setting: the fixed kinds, and the ones the user adds."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_session
from app.models import User
from app.thoughts.categories import (
    FIXED_CATEGORIES,
    add_category,
    added_categories,
    remove_category,
)

router = APIRouter(prefix="/api/settings/categories")


class Categories(BaseModel):
    fixed: list[str]
    added: list[str]


class CategoryIn(BaseModel):
    name: str


async def _categories(session: AsyncSession, user: User) -> Categories:
    return Categories(fixed=list(FIXED_CATEGORIES), added=await added_categories(session, user))


@router.get("", response_model=Categories)
async def read_categories(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Categories:
    return await _categories(session, user)


@router.post("", response_model=Categories, status_code=201)
async def create_category(
    body: CategoryIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Categories:
    await add_category(session, user, body.name)
    return await _categories(session, user)


@router.delete("/{name}", status_code=204)
async def delete_category(
    name: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await remove_category(session, user, name)
    return Response(status_code=204)
