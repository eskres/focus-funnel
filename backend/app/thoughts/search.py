"""Hybrid thought search: by meaning and by words, merged, in one SQL statement.

Meaning compares the query vector with every entry of the user's active
index (exact, no approximate index). Words use Postgres full-text search
with the `english` configuration, the query's words OR-joined. The two
rankings are merged by reciprocal rank fusion. A thought passes when its
similarity reaches the model's threshold, or it holds a large enough share
of the query's words. See openspec thought-storage design decision 5.

A search can also filter by the thought's own date (`dated_from`, `dated_to`):
only dated thoughts whose days overlap them pass. It can filter by status and
by category too. With any of these filters and no query, the search lists the
thoughts that pass, with no provider call: in date order with a date filter
(thought-dates design decision 4), newest filed first without one
(thought-status design decision 12).
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo

import httpx2
from sqlalchemy import exists, func, nulls_first, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import SearchConfig, get_chat_config
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.models import SearchIndex, Thought, User
from app.thoughts.indexing import (
    ACTIVE,
    embed_for_index,
    index_with_status,
    missing_thoughts,
    thought_pieces,
)
from app.thoughts.store import TS_CONFIG, clean_tags

logger = logging.getLogger(__name__)


@dataclass
class Hit:
    thought: Thought
    similarity: float | None
    keyword_rank: float | None
    # The best-matching entry's chunk, when the match came by meaning.
    chunk: int | None
    excerpt: str | None = None


@dataclass
class SearchResult:
    hits: list[Hit] = field(default_factory=list)
    # How many thoughts passed the cut-off, including those past the limit.
    total: int = 0
    # Set when the search ran by words only, with the reason.
    words_only: ApiError | None = None
    # The provider of the embedding model the search used or tried.
    embedding_provider: str | None = None

    @property
    def rebuild_needed(self) -> bool:
        return self.words_only is not None and self.words_only.code == ErrorCode.EMBEDDING_MISMATCH


def _as_start(value: date | datetime | None, zone: tzinfo | None = None) -> datetime | None:
    """A start date is the user's local midnight in `zone` (UTC when not given)."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min, tzinfo=zone or UTC)


def _as_end(value: date | datetime | None, zone: tzinfo | None = None) -> datetime | None:
    """An end date includes its whole local day in `zone` (UTC when not given)."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.combine(value + timedelta(days=1), time.min, tzinfo=zone or UTC)


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


_FILTERED = """
filtered AS (
    SELECT id FROM thoughts
    WHERE user_id = :user_id
      AND (CAST(:tags AS text[]) IS NULL OR tags && CAST(:tags AS text[]))
      AND (CAST(:since AS timestamptz) IS NULL OR created_at >= CAST(:since AS timestamptz))
      AND (CAST(:until AS timestamptz) IS NULL OR created_at < CAST(:until AS timestamptz))
      AND (CAST(:dated_from AS date) IS NULL
           OR coalesce(ends_on, starts_on) >= CAST(:dated_from AS date))
      AND (CAST(:dated_to AS date) IS NULL OR starts_on <= CAST(:dated_to AS date))
      AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
      AND (CAST(:category AS text) IS NULL OR category = CAST(:category AS text))
)"""

_MEANING = """
meaning_best AS (
    SELECT DISTINCT ON (e.thought_id)
        e.thought_id, e.chunk, e.embedding <=> CAST(:query_vector AS halfvec) AS distance
    FROM thought_embeddings e
    JOIN filtered f ON f.id = e.thought_id
    WHERE e.index_id = :index_id
    ORDER BY e.thought_id, distance
),
meaning AS (
    SELECT thought_id, chunk, distance, row_number() OVER (ORDER BY distance) AS rank
    FROM (SELECT * FROM meaning_best ORDER BY distance LIMIT :candidates) best
)"""

_NO_MEANING = """
meaning AS (
    SELECT NULL::uuid AS thought_id, NULL::int AS chunk, NULL::float8 AS distance,
           NULL::bigint AS rank
    WHERE false
)"""

_WORDS = f"""
terms AS (
    SELECT CAST(replace(CAST(plainto_tsquery('{TS_CONFIG}', :query) AS text), '&', '|')
                AS tsquery) AS any_term,
           tsvector_to_array(to_tsvector('{TS_CONFIG}', :query)) AS lexemes
),
words AS (
    SELECT thought_id, keyword_rank,
           (SELECT count(*) FROM unnest(terms.lexemes) AS lexeme
            WHERE best.search_tsv @@ CAST(quote_literal(lexeme) AS tsquery))::float8
               / greatest(cardinality(terms.lexemes), 1) AS word_share,
           row_number() OVER (ORDER BY keyword_rank DESC) AS rank
    FROM (
        SELECT t.id AS thought_id, t.search_tsv,
               ts_rank_cd(t.search_tsv, terms.any_term) AS keyword_rank
        FROM thoughts t
        JOIN filtered f ON f.id = t.id
        CROSS JOIN terms
        WHERE t.search_tsv @@ terms.any_term
        ORDER BY keyword_rank DESC
        LIMIT :candidates
    ) best
    CROSS JOIN terms
)"""

_MERGE = """
merged AS (
    SELECT coalesce(m.thought_id, w.thought_id) AS thought_id,
           coalesce(1.0 / (:rrf_k + m.rank), 0) + coalesce(1.0 / (:rrf_k + w.rank), 0) AS score,
           1 - m.distance AS similarity,
           m.chunk,
           w.keyword_rank,
           coalesce(w.word_share, 0) AS word_share
    FROM meaning m
    FULL OUTER JOIN words w ON w.thought_id = m.thought_id
),
passed AS (
    SELECT merged.*, t.created_at
    FROM merged JOIN thoughts t ON t.id = merged.thought_id
    WHERE merged.similarity >= :min_similarity
       OR merged.word_share >= :min_word_share
)
SELECT thought_id, similarity, keyword_rank, chunk, count(*) OVER () AS total
FROM passed
ORDER BY {order}
LIMIT :limit"""


def build_query(*, with_meaning: bool, newest_first: bool) -> str:
    order = "created_at DESC, score DESC" if newest_first else "score DESC, created_at DESC"
    parts = [_FILTERED, _MEANING if with_meaning else _NO_MEANING, _WORDS]
    return "WITH " + ",".join(parts) + "," + _MERGE.format(order=order)


def _words(value: str) -> list[str]:
    return re.findall(r"[\w-]+", value.lower())


def excerpt(raw_text: str, start: int, end: int, query: str, size: int) -> str:
    """At most `size` characters of the chunk, around its first query word if any."""
    chunk = raw_text[start:end]
    lowered = chunk.lower()
    positions = [lowered.find(word) for word in _words(query) if lowered.find(word) >= 0]
    centre = min(positions) if positions else 0
    begin = max(0, min(centre - size // 3, len(chunk) - size))
    piece = chunk[begin : begin + size]
    # Cut at word boundaries, and mark what was cut.
    if begin > 0:
        piece = piece.split(" ", 1)[-1] if " " in piece else piece
        piece = "…" + piece
    if begin + size < len(chunk):
        piece = piece.rsplit(" ", 1)[0] + "…"
    return " ".join(piece.split())


def raw_text_excerpt(thought: Thought, hit_chunk: int | None, query: str, size: int) -> str | None:
    """An excerpt when the best match was in the raw text, not the title, tags, or summary."""
    if not thought.raw_text:
        return None
    parts = thought_pieces(thought)
    if hit_chunk is not None and hit_chunk > 0:
        piece = next((p for p in parts if p.chunk == hit_chunk), None)
        if piece is not None and piece.start_char is not None:
            return excerpt(thought.raw_text, piece.start_char, piece.end_char, query, size)
        return None
    # The head matched best by meaning, or nothing did: the raw text still
    # holds the match when it has query words the head lacks.
    head = parts[0].text.lower()
    words = _words(query)
    raw = thought.raw_text.lower()
    if any(word in raw for word in words) and not any(word in head for word in words):
        return excerpt(thought.raw_text, 0, len(thought.raw_text), query, size)
    return None


def _list_filters(
    user: User, *, tags, since, until, dated_from, dated_to, status, category, zone
) -> list:
    """The filtered CTE's conditions, as SQLAlchemy, for the list with no query.

    Scoped by `user_id` like the CTE. Only dated thoughts pass a date filter.
    """
    conditions = [Thought.user_id == user.id]
    if dated_from is not None or dated_to is not None:
        conditions.append(Thought.starts_on.is_not(None))
    if status is not None:
        conditions.append(Thought.status == status)
    if category is not None:
        conditions.append(Thought.category == category)
    if tags:
        conditions.append(Thought.tags.overlap(tags))
    if since is not None:
        conditions.append(Thought.created_at >= _as_start(since, zone))
    if until is not None:
        conditions.append(Thought.created_at < _as_end(until, zone))
    if dated_from is not None:
        conditions.append(func.coalesce(Thought.ends_on, Thought.starts_on) >= dated_from)
    if dated_to is not None:
        conditions.append(Thought.starts_on <= dated_to)
    return conditions


async def list_filtered(
    session: AsyncSession,
    user: User,
    *,
    config: SearchConfig,
    tags: list[str] | None = None,
    since: date | datetime | None = None,
    until: date | datetime | None = None,
    dated_from: date | None = None,
    dated_to: date | None = None,
    status: str | None = None,
    category: str | None = None,
    zone: tzinfo | None = None,
) -> SearchResult:
    """The user's thoughts that pass the filters, with no query.

    With a date filter, only dated thoughts, in date order: by start day, a
    day with no time before one with a time, then by start time and filing
    time. Without one, newest filed first. No ranking and no provider call;
    `total` counts every thought that passed, past the limit too.
    """
    dated = dated_from is not None or dated_to is not None
    conditions = _list_filters(
        user,
        tags=clean_tags(tags) or None,
        since=since,
        until=until,
        dated_from=dated_from,
        dated_to=dated_to,
        status=status,
        category=category,
        zone=zone,
    )
    order = (
        (Thought.starts_on, nulls_first(Thought.starts_at), Thought.created_at, Thought.id)
        if dated
        else (Thought.created_at.desc(), Thought.id)
    )
    rows = (
        await session.execute(
            select(Thought, func.count().over().label("total"))
            .where(*conditions)
            .order_by(*order)
            .limit(config.limit)
        )
    ).all()
    if not rows:
        return SearchResult()
    hits = [
        Hit(thought=row.Thought, similarity=None, keyword_rank=None, chunk=None) for row in rows
    ]
    return SearchResult(hits=hits, total=rows[0].total)


def _no_query_and_no_filter() -> ApiError:
    return ApiError(
        422,
        ErrorCode.VALIDATION_ERROR,
        "query: give the words to look for, or the days the thought is dated, "
        "its status, or its category",
    )


async def search_thoughts(
    session: AsyncSession,
    user: User,
    query: str | None,
    *,
    settings: Settings,
    tags: list[str] | None = None,
    since: date | datetime | None = None,
    until: date | datetime | None = None,
    newest_first: bool = False,
    conversation_id: uuid.UUID | None = None,
    http_client: httpx2.AsyncClient | None = None,
    config: SearchConfig | None = None,
    zone: tzinfo | None = None,
    dated_from: date | None = None,
    dated_to: date | None = None,
    status: str | None = None,
    category: str | None = None,
) -> SearchResult:
    """The user's thoughts that match the query, best first. See the module docstring.

    `since` and `until` given as dates are the user's local days in `zone`
    (UTC when not given). `dated_from` and `dated_to` are days of the
    thought's own date, compared as written. `status` and `category` keep
    only thoughts with that stored status or category. With any of these
    four the query may be None or empty: the search then lists the thoughts
    that pass, in date order with a date filter and newest filed first
    without one, with no embedding call and no backfill. Without them, a
    missing query raises validation_error naming `query`.

    Never raises for a provider problem: the search then runs by words only
    and `words_only` says why.
    """
    config = config or get_chat_config().search
    tags = clean_tags(tags) or None
    query = query.strip() if isinstance(query, str) else ""
    status = status or None
    category = category or None
    filtered = any(value is not None for value in (dated_from, dated_to, status, category))
    if not query and not filtered:
        raise _no_query_and_no_filter()
    has_thoughts = select(Thought.id).where(Thought.user_id == user.id)
    if tags:
        has_thoughts = has_thoughts.where(Thought.tags.overlap(tags))
    if not (await session.execute(select(exists(has_thoughts)))).scalar():
        return SearchResult()
    if not query:
        return await list_filtered(
            session,
            user,
            config=config,
            tags=tags,
            since=since,
            until=until,
            dated_from=dated_from,
            dated_to=dated_to,
            status=status,
            category=category,
            zone=zone,
        )

    active = await index_with_status(session, user.id, ACTIVE)
    backfill = await missing_thoughts(session, user.id, active, config.backfill_batch)
    outcome = await embed_for_index(
        session,
        user,
        active,
        [(thought.id, thought_pieces(thought)) for thought in backfill],
        settings=settings,
        extra_texts=[query],
        extra_instruction=config.query_instruction_for,
        conversation_id=conversation_id,
        http_client=http_client,
    )
    await session.commit()
    index = outcome.index
    with_meaning = outcome.error is None and index is not None

    result = await rank(
        session,
        user,
        query,
        index=index if with_meaning else None,
        query_vector=outcome.extra_vectors[0] if with_meaning else None,
        tags=tags,
        since=since,
        until=until,
        newest_first=newest_first,
        config=config,
        zone=zone,
        dated_from=dated_from,
        dated_to=dated_to,
        status=status,
        category=category,
    )
    result.words_only = outcome.error
    result.embedding_provider = (
        index.embedding_provider if index is not None else settings.embedding_provider
    )
    return result


async def rank(
    session: AsyncSession,
    user: User,
    query: str,
    *,
    index: SearchIndex | None,
    query_vector: list[float] | None,
    config: SearchConfig,
    tags: list[str] | None = None,
    since: date | datetime | None = None,
    until: date | datetime | None = None,
    newest_first: bool = False,
    use_words: bool = True,
    zone: tzinfo | None = None,
    dated_from: date | None = None,
    dated_to: date | None = None,
    status: str | None = None,
    category: str | None = None,
    min_similarity: float | None = None,
    limit: int | None = None,
) -> SearchResult:
    """Run the ranking SQL for a query already embedded (or not, for words only).

    The evaluation calls this directly with stored vectors; use_words=False
    ranks by meaning alone, for comparison. `min_similarity` and `limit`
    replace the configured cut-off for the index's model and the result limit.
    """
    with_meaning = index is not None and query_vector is not None
    params = {
        "user_id": user.id,
        "tags": clean_tags(tags) or None,
        "since": _as_start(since, zone),
        "until": _as_end(until, zone),
        "dated_from": dated_from,
        "dated_to": dated_to,
        "status": status,
        "category": category,
        "query": query if use_words else "",
        "candidates": config.candidates,
        "rrf_k": config.rrf_k,
        "min_word_share": config.min_word_share,
        "limit": limit if limit is not None else config.limit,
        "min_similarity": 2.0,
    }
    if with_meaning:
        params["query_vector"] = _vector_literal(query_vector)
        params["index_id"] = index.id
        params["min_similarity"] = (
            min_similarity
            if min_similarity is not None
            else config.min_similarity_for(index.embedding_model)
        )
    # Plan for these values each time: a generic plan for the prepared
    # statement, which Postgres switches to after five runs, is twice as slow.
    await session.execute(text("SET LOCAL plan_cache_mode = force_custom_plan"))
    rows = (
        await session.execute(
            text(build_query(with_meaning=with_meaning, newest_first=newest_first)), params
        )
    ).all()
    if not rows:
        return SearchResult()

    ids = [row.thought_id for row in rows]
    thoughts = {
        thought.id: thought
        for thought in (
            await session.execute(
                select(Thought).where(Thought.id.in_(ids), Thought.user_id == user.id)
            )
        ).scalars()
    }
    hits = []
    for row in rows:
        thought = thoughts.get(row.thought_id)
        if thought is None:
            continue
        hits.append(
            Hit(
                thought=thought,
                similarity=row.similarity,
                keyword_rank=row.keyword_rank,
                chunk=row.chunk,
                excerpt=raw_text_excerpt(thought, row.chunk, query, config.excerpt_chars),
            )
        )
    return SearchResult(hits=hits, total=rows[0].total)


async def search_by_vector(
    session: AsyncSession,
    user: User,
    words: str,
    *,
    index: SearchIndex | None,
    vector: list[float] | None,
    min_similarity: float,
    limit: int,
    config: SearchConfig,
) -> SearchResult:
    """The user's thoughts that match a vector the caller already has, or
    `words` by the word-share rule, best first, with no embedding call.

    The similar-thought check (thought-appending design decision 4) embeds
    every part's query in one request and then calls this once per part.
    The ranking is the search's: meaning and words merged, with no age
    penalty. Without an index or a vector it matches by words only.
    """
    if session.bind.dialect.name != "postgresql":
        return SearchResult()
    return await rank(
        session,
        user,
        words,
        index=index if vector is not None else None,
        query_vector=vector,
        config=config,
        min_similarity=min_similarity,
        limit=limit,
    )
