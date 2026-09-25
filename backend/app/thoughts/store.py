"""Storing, updating, reading, and deleting thoughts.

Postgres holds every thought. Storing never fails for a provider reason: a
thought whose embedding call fails is saved, found by its words at once, and
gets its embeddings from a later call (see indexing.py). Only invalid fields
fail a store. These operations run on Postgres only.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx2
from sqlalchemy import delete, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.chat.config import get_chat_config
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.models import SearchIndex, Thought, ThoughtEmbedding, User
from app.thoughts.chunking import Piece, pieces
from app.thoughts.indexing import (
    ACTIVE,
    BUILDING,
    RETIRED,
    embed_for_index,
    index_with_status,
    missing_thoughts,
    thought_pieces,
)

logger = logging.getLogger(__name__)

MAX_TITLE = 200
MAX_SUMMARY = 4_000
MAX_RAW_TEXT = 20_000
MAX_TAGS = 20
MAX_TAG = 50
# The text search configuration: English stop words dropped and words matched
# by their stem. Changing it needs every thought's search_tsv written again.
TS_CONFIG = "english"
TS_CONFIG_SQL = literal_column(f"'{TS_CONFIG}'::regconfig")


def invalid(field: str, message: str) -> ApiError:
    return ApiError(422, ErrorCode.VALIDATION_ERROR, f"{field}: {message}")


def thought_not_found() -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND, "No such thought.")


def clean_tags(tags: list[str] | None) -> list[str]:
    """Trimmed, lowercased, without a leading `#`, empty, or repeated tags, in their first order.

    The search result shows tags as `#tag`, and the chat model passes them back that way.
    """
    if tags is None:
        return []
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise invalid("tags", "must be a list of strings")
    cleaned: list[str] = []
    for tag in tags:
        tag = " ".join(tag.split()).lower().lstrip("#").strip()
        if tag and tag not in cleaned:
            cleaned.append(tag)
    if len(cleaned) > MAX_TAGS:
        raise invalid("tags", f"at most {MAX_TAGS} tags")
    for tag in cleaned:
        if len(tag) > MAX_TAG:
            raise invalid("tags", f"each tag must be at most {MAX_TAG} characters")
    return cleaned


def _text(field: str, value: Any, limit: int, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise invalid(field, "must be text")
    value = value.strip()
    if not value:
        if required:
            raise invalid(field, "must not be empty")
        return None
    if len(value) > limit:
        raise invalid(field, f"must be at most {limit:,} characters")
    return value


@dataclass(frozen=True)
class ThoughtFields:
    title: str
    summary: str
    tags: list[str]
    raw_text: str | None
    category: str | None


def check_fields(
    title: Any, summary: Any, tags: Any, raw_text: Any = None, category: Any = None
) -> ThoughtFields:
    return ThoughtFields(
        title=_text("title", title, MAX_TITLE, required=True),
        summary=_text("summary", summary, MAX_SUMMARY, required=True),
        tags=clean_tags(tags),
        raw_text=_text("raw_text", raw_text, MAX_RAW_TEXT, required=False),
        category=_text("category", category, MAX_TAG, required=False),
    )


def search_vector(
    title: str, tags: list[str], summary: str, raw_text: str | None
) -> ColumnElement:
    """The weighted words search matches on: title and tags A, summary B, raw text C."""

    def weighted(text: str, weight: str) -> ColumnElement:
        return func.setweight(
            func.to_tsvector(TS_CONFIG_SQL, text), literal_column(f"'{weight}'::\"char\"")
        )

    return (
        weighted(title, "A")
        .op("||")(weighted(" ".join(tags), "A"))
        .op("||")(weighted(summary, "B"))
        .op("||")(weighted(raw_text or "", "C"))
    )


@dataclass
class StoreOutcome:
    thought: Thought
    # False when the thought was saved without embeddings; they are filled in later.
    embedded: bool
    error: ApiError | None = None


async def _other_index_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.execute(
        select(SearchIndex.id).where(SearchIndex.user_id == user_id, SearchIndex.status != RETIRED)
    )
    return list(rows.scalars())


async def _index_thought(
    session: AsyncSession,
    user: User,
    thought: Thought,
    new_pieces: list[Piece],
    *,
    add_thought: bool,
    settings: Settings,
    conversation_id: uuid.UUID | None,
    http_client: httpx2.AsyncClient | None,
) -> StoreOutcome:
    """Embed a new or changed thought, with some missing ones, into the user's indexes."""
    batch = get_chat_config().search.backfill_batch
    active = await index_with_status(session, user.id, ACTIVE)
    backfill = [
        other
        for other in await missing_thoughts(session, user.id, active, batch)
        if other.id != thought.id
    ]
    items = [(thought.id, new_pieces)] + [(other.id, thought_pieces(other)) for other in backfill]
    outcome = await embed_for_index(
        session,
        user,
        active,
        items,
        settings=settings,
        add_first=[thought] if add_thought else None,
        conversation_id=conversation_id,
        http_client=http_client,
    )
    embedded = outcome.error is None
    if not embedded and add_thought:
        session.add(thought)
    building = await index_with_status(session, user.id, BUILDING)
    if building is not None:
        # During a rebuild the new index gets the thought too, with its own
        # model. If this fails, the rebuild's final fill adds it.
        await embed_for_index(
            session,
            user,
            building,
            [(thought.id, new_pieces)],
            settings=settings,
            conversation_id=conversation_id,
            http_client=http_client,
        )
    return StoreOutcome(thought=thought, embedded=embedded, error=outcome.error)


async def add_thought(
    session: AsyncSession,
    user: User,
    *,
    title: Any,
    summary: Any,
    tags: Any = None,
    raw_text: Any = None,
    category: Any = None,
    settings: Settings,
    conversation_id: uuid.UUID | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> StoreOutcome:
    """Add a thought for the user and index it, without committing, so the
    caller can commit it with other changes. Raises validation_error only."""
    fields = check_fields(title, summary, tags, raw_text, category)
    thought = Thought(
        id=uuid.uuid4(),
        user_id=user.id,
        title=fields.title,
        summary=fields.summary,
        tags=fields.tags,
        raw_text=fields.raw_text,
        category=fields.category,
        search_tsv=search_vector(fields.title, fields.tags, fields.summary, fields.raw_text),
    )
    outcome = await _index_thought(
        session,
        user,
        thought,
        pieces(fields.title, fields.tags, fields.summary, fields.raw_text),
        add_thought=True,
        settings=settings,
        conversation_id=conversation_id,
        http_client=http_client,
    )
    await session.flush()
    return outcome


async def store_thought(
    session: AsyncSession,
    user: User,
    *,
    settings: Settings,
    conversation_id: uuid.UUID | None = None,
    http_client: httpx2.AsyncClient | None = None,
    **fields: Any,
) -> StoreOutcome:
    """Store a thought for the user and index it. Raises validation_error only."""
    outcome = await add_thought(
        session,
        user,
        settings=settings,
        conversation_id=conversation_id,
        http_client=http_client,
        **fields,
    )
    await session.commit()
    await session.refresh(outcome.thought)
    return outcome


async def known_tags(session: AsyncSession, user: User, limit: int) -> list[str]:
    """The user's tags, most used first, then by name, up to limit.

    Postgres only: on another database the user has no known tags.
    """
    if session.bind.dialect.name != "postgresql":
        return []
    tag = func.unnest(Thought.tags).table_valued("tag").render_derived()
    uses = func.count()
    rows = await session.execute(
        select(tag.c.tag)
        .select_from(Thought)
        .join(tag, literal_column("true"))
        .where(Thought.user_id == user.id)
        .group_by(tag.c.tag)
        .order_by(uses.desc(), tag.c.tag)
        .limit(limit)
    )
    return list(rows.scalars())


async def get_thought(session: AsyncSession, user: User, thought_id: uuid.UUID) -> Thought:
    """The user's thought, or not_found for a missing one or another user's."""
    thought = (
        await session.execute(
            select(Thought).where(Thought.id == thought_id, Thought.user_id == user.id)
        )
    ).scalar_one_or_none()
    if thought is None:
        raise thought_not_found()
    return thought


_UNSET: Any = object()


async def update_thought(
    session: AsyncSession,
    user: User,
    thought_id: uuid.UUID,
    *,
    title: Any = _UNSET,
    summary: Any = _UNSET,
    tags: Any = _UNSET,
    raw_text: Any = _UNSET,
    category: Any = _UNSET,
    settings: Settings,
    conversation_id: uuid.UUID | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> StoreOutcome:
    """Change some of a thought's fields, and index again only what changed.

    A new title, summary, or raw text replaces all the thought's entries; new
    tags replace its head; a new category touches no entry.
    """
    thought = await get_thought(session, user, thought_id)

    def pick(value: Any, current: Any) -> Any:
        return current if value is _UNSET else value

    fields = check_fields(
        pick(title, thought.title),
        pick(summary, thought.summary),
        pick(tags, list(thought.tags or [])),
        pick(raw_text, thought.raw_text),
        pick(category, thought.category),
    )
    content_changed = (fields.title, fields.summary, fields.raw_text) != (
        thought.title,
        thought.summary,
        thought.raw_text,
    )
    tags_changed = fields.tags != list(thought.tags or [])

    thought.title, thought.summary, thought.raw_text = fields.title, fields.summary, fields.raw_text
    thought.tags, thought.category = fields.tags, fields.category
    if not (content_changed or tags_changed):
        await session.commit()
        await session.refresh(thought)
        return StoreOutcome(thought=thought, embedded=True)

    thought.search_tsv = search_vector(fields.title, fields.tags, fields.summary, fields.raw_text)
    index_ids = await _other_index_ids(session, user.id)
    if index_ids:
        # Old entries go now, so search by meaning never finds the old wording.
        stale = delete(ThoughtEmbedding).where(
            ThoughtEmbedding.thought_id == thought.id,
            ThoughtEmbedding.index_id.in_(index_ids),
        )
        if not content_changed:
            stale = stale.where(ThoughtEmbedding.chunk == 0)
        await session.execute(stale)
    all_pieces = pieces(fields.title, fields.tags, fields.summary, fields.raw_text)
    new_pieces = all_pieces if content_changed else all_pieces[:1]
    outcome = await _index_thought(
        session,
        user,
        thought,
        new_pieces,
        add_thought=False,
        settings=settings,
        conversation_id=conversation_id,
        http_client=http_client,
    )
    await session.commit()
    await session.refresh(thought)
    return outcome


async def delete_thought(session: AsyncSession, user: User, thought_id: uuid.UUID) -> None:
    """Delete the user's thought; its entries go with it in the same transaction."""
    result = await session.execute(
        delete(Thought).where(Thought.id == thought_id, Thought.user_id == user.id)
    )
    if result.rowcount == 0:
        raise thought_not_found()
    await session.commit()
