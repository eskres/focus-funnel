"""The user's thoughts, newest filed first, a page at a time (the Library page).

One owner-scoped select on `ix_thoughts_user_id_created_at`, with only the
columns a row shows, the filters of thought-library design decision 6, and a
keyset cursor (design decision 3). It reads no search columns and calls no
provider, so it works with no key and with an index that needs a rebuild.
"""

import base64
import binascii
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.errors import ApiError
from app.models import Thought, User
from app.ownership import owned_by
from app.thoughts.categories import clean_name
from app.thoughts.search import _as_end, _as_start
from app.thoughts.store import clean_tag, invalid

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
_CURSOR = re.compile(r"[A-Za-z0-9_-]+")

# What a row shows; any other column read from these rows would lazy-load on
# the async session and fail (design decision 5).
ROW_COLUMNS = (
    Thought.id,
    Thought.title,
    Thought.category,
    Thought.tags,
    Thought.status,
    Thought.created_at,
    Thought.starts_on,
    Thought.starts_at,
    Thought.ends_on,
    Thought.ends_at,
    Thought.time_zone,
)


@dataclass(frozen=True)
class Cursor:
    """The place after the last row shown: its filed time and id."""

    created_at: datetime
    id: uuid.UUID


@dataclass
class LibraryPage:
    items: list[Thought]
    next_cursor: str | None


def bad_cursor() -> ApiError:
    return invalid("cursor", "not a valid cursor")


def encode_cursor(created_at: datetime, thought_id: uuid.UUID) -> str:
    """base64url of `<UTC time, to the microsecond>|<id>`, with no padding."""
    moment = created_at.astimezone(UTC).isoformat(timespec="microseconds")
    return base64.urlsafe_b64encode(f"{moment}|{thought_id}".encode()).rstrip(b"=").decode()


def decode_cursor(text: str) -> Cursor:
    """The cursor's place, or validation_error `cursor: not a valid cursor`
    for anything encode_cursor() would not have written."""
    if not isinstance(text, str) or not _CURSOR.fullmatch(text):
        raise bad_cursor()
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise bad_cursor() from None
    parts = raw.split("|")
    if len(parts) != 2:
        raise bad_cursor()
    try:
        moment = datetime.fromisoformat(parts[0])
        if moment.tzinfo is None:
            raise bad_cursor()
        # Converted here, as asyncpg would convert it when binding, so a time
        # out of range is a 422 and not a 500.
        moment = moment.astimezone(UTC)
        thought_id = uuid.UUID(parts[1])
    except (ValueError, OverflowError):
        raise bad_cursor() from None
    return Cursor(moment, thought_id)


def library_query(
    user: User,
    *,
    limit: int = DEFAULT_LIMIT,
    cursor: Cursor | None = None,
    category: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    filed_from: date | None = None,
    filed_to: date | None = None,
    zone: ZoneInfo | None = None,
) -> Select:
    """The page's select: `limit + 1` rows, newest filed first.

    `category` and `tag` are taken as cleaned; `status` as checked.
    """
    query = (
        select(Thought)
        .where(owned_by(Thought, user))
        .options(load_only(*ROW_COLUMNS))
        .order_by(Thought.created_at.desc(), Thought.id.desc())
        .limit(limit + 1)
    )
    if category:
        query = query.where(Thought.category == category)
    if tag:
        query = query.where(Thought.tags.contains([tag]))
    if status is not None:
        query = query.where(Thought.status == status)
    if filed_from is not None:
        query = query.where(Thought.created_at >= _as_start(filed_from, zone))
    if filed_to is not None:
        query = query.where(Thought.created_at < _as_end(filed_to, zone))
    if cursor is not None:
        # The plain range is redundant; it gives the planner a range on the
        # index rather than an OR alone (design decision 3).
        query = query.where(
            Thought.created_at <= cursor.created_at,
            or_(Thought.created_at < cursor.created_at, Thought.id < cursor.id),
        )
    return query


async def list_thoughts(
    session: AsyncSession,
    user: User,
    *,
    limit: int = DEFAULT_LIMIT,
    cursor: Cursor | None = None,
    category: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    filed_from: date | None = None,
    filed_to: date | None = None,
    zone: ZoneInfo | None = None,
) -> LibraryPage:
    """One page of the user's thoughts and the cursor of the next, null on the last.

    A category or tag empty after cleaning is no filter. One that still holds
    NUL matches nothing, and no query runs: Postgres text cannot hold it, and
    asyncpg would refuse to bind it (design decision 6).
    """
    category = clean_name(category) if category is not None else None
    tag = clean_tag(tag) if tag is not None else None
    if "\x00" in (category or "") or "\x00" in (tag or ""):
        return LibraryPage(items=[], next_cursor=None)
    query = library_query(
        user,
        limit=limit,
        cursor=cursor,
        category=category,
        tag=tag,
        status=status,
        filed_from=filed_from,
        filed_to=filed_to,
        zone=zone,
    )
    rows = list((await session.execute(query)).scalars())
    if len(rows) <= limit:
        return LibraryPage(items=rows, next_cursor=None)
    last = rows[limit - 1]
    return LibraryPage(items=rows[:limit], next_cursor=encode_cursor(last.created_at, last.id))
