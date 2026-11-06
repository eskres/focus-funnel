"""The user's thoughts a page at a time, for the Library page; one stored
thought, its origin and additions, for the detail view; and changing or
deleting it, or undoing its last addition."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

import httpx2
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.models import User
from app.providers import get_provider_http_client
from app.thoughts.additions import list_additions, undo_addition
from app.thoughts.categories import check_category
from app.thoughts.dates import when_of, zone_from
from app.thoughts.library import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, list_thoughts
from app.thoughts.store import (
    ThoughtOrigin,
    check_status,
    delete_thought,
    get_thought,
    get_thought_with_origin,
    list_upcoming,
    set_status,
    update_thought,
)

router = APIRouter(prefix="/api/thoughts")


class OriginOut(BaseModel):
    conversation_id: uuid.UUID
    conversation_title: str
    archived: bool
    proposal_id: uuid.UUID
    proposed_at: datetime


class AdditionOut(BaseModel):
    id: uuid.UUID
    added_at: datetime
    undone: bool
    # The conversation it came from, as it is titled now, and the proposal
    # whose card it was: /app/<conversation_id>?proposal=<proposal_id>.
    conversation_id: uuid.UUID
    conversation_title: str
    proposal_id: uuid.UUID


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
    # open or done, and when it last changed; null while it never changed.
    status: str
    status_changed_at: datetime | None
    # The conversation and proposal it was saved from; null when there is none,
    # or once that conversation is deleted.
    origin: OriginOut | None
    # Each addition from a later proposal, newest first; one whose
    # conversation was deleted is gone.
    additions: list[AdditionOut]


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
    # open or done; the thought store checks it, so a refusal names `status`.
    status: Any = None


def addition_view(row: Any) -> AdditionOut:
    """One addition as the API and the export show it. It reads the fields by
    attribute, so a dataclass and a labelled Row both work."""
    return AdditionOut(
        id=row.id,
        added_at=row.added_at,
        undone=row.undone,
        conversation_id=row.conversation_id,
        conversation_title=row.conversation_title,
        proposal_id=row.proposal_id,
    )


def thought_view(thought: Any, origin: ThoughtOrigin | None, additions: list[AdditionOut]) -> ThoughtOut:
    """A stored thought with its origin and additions, as GET /api/thoughts/{id}
    answers it and the export writes it (thought-export design decision 3)."""
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
        status=thought.status,
        status_changed_at=thought.status_changed_at,
        origin=OriginOut(**vars(origin)) if origin else None,
        additions=additions,
    )


async def thought_answer(session: AsyncSession, user: User, thought_id: uuid.UUID) -> ThoughtOut:
    """The user's thought with its origin. Another user's, and one that does
    not exist, are both not_found."""
    thought, origin = await get_thought_with_origin(session, user, thought_id)
    additions = await list_additions(session, user, thought.id)
    return thought_view(thought, origin, [addition_view(addition) for addition in additions])


class UpcomingItem(BaseModel):
    id: uuid.UUID
    title: str
    category: str | None
    when: dict[str, str | None]


class UpcomingOut(BaseModel):
    items: list[UpcomingItem]
    # True when more dated thoughts from that day on exist than the list shows.
    more: bool


def _empty_as_none(value: Any) -> Any:
    """An empty query parameter is read as absent (thought-library design decision 4)."""
    return None if value == "" else value


# The bounds sit inside the optional type, so None never meets them.
Limit = Annotated[
    Annotated[int, Field(ge=1, le=MAX_LIMIT)] | None, BeforeValidator(_empty_as_none)
]
# No zone's offset can overflow a day in this range, nor can _as_end's added day.
FiledDay = Annotated[
    Annotated[date, Field(ge=date(1900, 1, 1), le=date(9998, 12, 31))] | None,
    BeforeValidator(_empty_as_none),
]
Text = Annotated[str | None, BeforeValidator(_empty_as_none)]


class ThoughtRow(BaseModel):
    id: uuid.UUID
    title: str
    category: str | None
    tags: list[str]
    status: str
    created_at: datetime
    # The thought's own date, {start, end, time_zone}; null when it has none.
    when: dict[str, str | None] | None


class ThoughtList(BaseModel):
    items: list[ThoughtRow]
    # The cursor of the next page, with the same filters; null on the last page.
    next_cursor: str | None


@router.get("", response_model=ThoughtList)
async def library(
    limit: Annotated[Limit, Query()] = None,
    cursor: Annotated[Text, Query()] = None,
    status: Annotated[Text, Query()] = None,
    category: Annotated[Text, Query()] = None,
    tag: Annotated[Text, Query()] = None,
    filed_from: Annotated[FiledDay, Query()] = None,
    filed_to: Annotated[FiledDay, Query()] = None,
    time_zone: Annotated[Text, Query()] = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ThoughtList:
    """The user's thoughts, newest filed first, a page at a time.

    Filters are ANDed and each is optional: one category, one tag, one status,
    and filed days in the browser's zone. Needs no provider.
    """
    page = await list_thoughts(
        session,
        user,
        limit=limit if limit is not None else DEFAULT_LIMIT,
        cursor=decode_cursor(cursor) if cursor is not None else None,
        category=category,
        tag=tag,
        status=check_status(status) if status is not None else None,
        filed_from=filed_from,
        filed_to=filed_to,
        zone=zone_from(time_zone),
    )
    return ThoughtList(
        items=[
            ThoughtRow(
                id=row.id,
                title=row.title,
                category=row.category,
                tags=list(row.tags or []),
                status=row.status,
                created_at=row.created_at,
                when=when_of(row),
            )
            for row in page.items
        ],
        next_cursor=page.next_cursor,
    )


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

    A status change runs first and keeps updated_at; any other field moves it.

    Only what changed is embedded again; a new date or category is not
    embedded at all. An embedding failure does not fail
    the change, as for confirm: search finds it by its words at once, and the
    missing entries are filled in by the next call that reaches the provider.
    """
    fields = body.model_dump(exclude_unset=True)
    has_status = "status" in fields
    status = fields.pop("status", None)
    if has_status:
        # First, and with the other fields in one commit: a refused field
        # after it leaves the status as it was. It keeps updated_at.
        await set_status(session, user, thought_id, status)
    if "category" in fields:
        # The thought's own category stays a choice, even once the user removed it.
        current = await get_thought(session, user, thought_id)
        fields["category"] = await check_category(
            session, user, body.category, keep=current.category
        )
    if fields or not has_status:
        await update_thought(
            session, user, thought_id, settings=settings, http_client=http_client, **fields
        )
    else:
        await session.commit()
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


@router.post("/{thought_id}/additions/{addition_id}/undo", response_model=ThoughtOut)
async def undo_last_addition(
    thought_id: uuid.UUID,
    addition_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ThoughtOut:
    """Restore the summary, tags, category, and raw text the thought had
    before this addition, and answer the thought as GET does.

    Refused with 409 thought_changed, with the thought's current fields,
    unless it is the newest addition not undone and the thought has not
    changed since. The restored content is embedded again; a failure there
    does not fail the undo, as for an edit.
    """
    await undo_addition(
        session, user, thought_id, addition_id, settings=settings, http_client=http_client
    )
    return await thought_answer(session, user, thought_id)
