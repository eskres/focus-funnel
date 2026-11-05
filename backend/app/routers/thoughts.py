"""One stored thought and its origin, for the detail view, and changing or deleting it."""

import uuid
from datetime import date, datetime
from typing import Any

import httpx2
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.models import User
from app.providers import get_provider_http_client
from app.thoughts.categories import check_category
from app.thoughts.dates import when_of
from app.thoughts.store import (
    delete_thought,
    get_thought,
    get_thought_with_origin,
    list_upcoming,
    update_thought,
)

router = APIRouter(prefix="/api/thoughts")


class OriginOut(BaseModel):
    conversation_id: uuid.UUID
    conversation_title: str
    archived: bool
    proposal_id: uuid.UUID
    proposed_at: datetime


class ThoughtOut(BaseModel):
    id: uuid.UUID
    title: str
    summary: str
    tags: list[str]
    category: str | None
    raw_text: str | None
    # The thought's own date, {start, end, time_zone}; null when it has none.
    when: dict[str, str | None] | None
    created_at: datetime
    updated_at: datetime
    # The conversation and proposal it was saved from; null when there is none,
    # or once that conversation is deleted.
    origin: OriginOut | None


class ThoughtPatch(BaseModel):
    """The fields a user may change. A missing field is kept; the raw text is
    not one of them, so a body naming it is refused."""

    model_config = ConfigDict(extra="forbid")

    # The thought store checks the fields, so its messages name them.
    title: Any = None
    summary: Any = None
    tags: Any = None
    # Null or empty clears it.
    category: str | None = None
    # {start, end, time_zone}, with the browser's zone; null clears the date.
    # The thought store checks it, so a refusal names `when`.
    when: Any = None


async def thought_answer(session: AsyncSession, user: User, thought_id: uuid.UUID) -> ThoughtOut:
    """The user's thought with its origin. Another user's, and one that does
    not exist, are both not_found."""
    thought, origin = await get_thought_with_origin(session, user, thought_id)
    return ThoughtOut(
        id=thought.id,
        title=thought.title,
        summary=thought.summary,
        tags=list(thought.tags or []),
        category=thought.category,
        raw_text=thought.raw_text,
        when=when_of(thought),
        created_at=thought.created_at,
        updated_at=thought.updated_at,
        origin=OriginOut(**vars(origin)) if origin else None,
    )


class UpcomingItem(BaseModel):
    id: uuid.UUID
    title: str
    category: str | None
    when: dict[str, str | None]


class UpcomingOut(BaseModel):
    items: list[UpcomingItem]
    # True when more dated thoughts from that day on exist than the list shows.
    more: bool


# Declared before /{thought_id}, so "upcoming" is never read as an id.
@router.get("/upcoming", response_model=UpcomingOut)
async def upcoming_thoughts(
    from_day: date = Query(alias="from", description="The browser's local today, YYYY-MM-DD."),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UpcomingOut:
    """The user's dated thoughts from that day on, in date order, at most 200."""
    rows, more = await list_upcoming(session, user, from_day)
    return UpcomingOut(
        items=[
            UpcomingItem(id=row.id, title=row.title, category=row.category, when=when_of(row))
            for row in rows
        ],
        more=more,
    )


@router.get("/{thought_id}", response_model=ThoughtOut)
async def read_thought(
    thought_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ThoughtOut:
    """The user's thought. Another user's, and one that does not exist, are both not_found."""
    return await thought_answer(session, user, thought_id)


@router.patch("/{thought_id}", response_model=ThoughtOut)
async def change_thought(
    thought_id: uuid.UUID,
    body: ThoughtPatch,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ThoughtOut:
    """Change the fields the body names, and answer the thought as GET does.

    Only what changed is embedded again; a new date or category is not
    embedded at all. An embedding failure does not fail
    the change, as for confirm: search finds it by its words at once, and the
    missing entries are filled in by the next call that reaches the provider.
    """
    fields = body.model_dump(exclude_unset=True)
    if "category" in fields:
        # The thought's own category stays a choice, even once the user removed it.
        current = await get_thought(session, user, thought_id)
        fields["category"] = await check_category(
            session, user, body.category, keep=current.category
        )
    await update_thought(
        session, user, thought_id, settings=settings, http_client=http_client, **fields
    )
    return await thought_answer(session, user, thought_id)


@router.delete("/{thought_id}", status_code=204)
async def remove_thought(
    thought_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete the thought and its search entries. The proposal it was saved
    from keeps the part's thought_id, so the part stays filed."""
    await delete_thought(session, user, thought_id)
    return Response(status_code=204)
