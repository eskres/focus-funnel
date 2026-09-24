"""Keeping a user's search index in step with their thoughts.

Store, search, and the rebuild job share this. Embeddings for a thought are
written with the thought when the provider answers, and otherwise filled in
later: every call that goes to the provider anyway also carries up to
`backfill_batch` texts of thoughts that lack entries. A thought lacks entries
when its index has no head (chunk 0) row for it.
"""

import logging
import uuid
from dataclasses import dataclass, field

import httpx2
from sqlalchemy import delete, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ApiError, embedding_mismatch
from app.models import SearchIndex, Thought, ThoughtEmbedding, User
from app.thoughts.chunking import Piece, pieces
from app.thoughts.embeddings import EmbeddingChoice, embed_texts, resolve_embedding_model

logger = logging.getLogger(__name__)

ACTIVE = "active"
BUILDING = "building"
RETIRED = "retired"


def thought_pieces(thought: Thought) -> list[Piece]:
    return pieces(thought.title, list(thought.tags or []), thought.summary, thought.raw_text)


async def index_with_status(
    session: AsyncSession, user_id: uuid.UUID, status: str
) -> SearchIndex | None:
    return (
        await session.execute(
            select(SearchIndex).where(SearchIndex.user_id == user_id, SearchIndex.status == status)
        )
    ).scalar_one_or_none()


async def missing_thoughts(
    session: AsyncSession, user_id: uuid.UUID, index: SearchIndex | None, text_budget: int
) -> list[Thought]:
    """The user's oldest thoughts without entries in this index, within a text budget.

    With no index, every thought lacks entries. At least one thought is
    returned when any is missing, however many chunks it has.
    """
    query = select(Thought).where(Thought.user_id == user_id)
    if index is not None:
        has_head = exists().where(
            ThoughtEmbedding.index_id == index.id,
            ThoughtEmbedding.thought_id == Thought.id,
            ThoughtEmbedding.chunk == 0,
        )
        query = query.where(~has_head)
    query = query.order_by(Thought.created_at, Thought.id).limit(max(text_budget, 1))
    chosen, texts = [], 0
    for thought in (await session.execute(query)).scalars():
        count = len(thought_pieces(thought))
        if chosen and texts + count > text_budget:
            break
        chosen.append(thought)
        texts += count
    return chosen


async def count_missing(session: AsyncSession, user_id: uuid.UUID, index: SearchIndex) -> int:
    has_head = exists().where(
        ThoughtEmbedding.index_id == index.id,
        ThoughtEmbedding.thought_id == Thought.id,
        ThoughtEmbedding.chunk == 0,
    )
    query = select(func.count()).select_from(Thought).where(Thought.user_id == user_id, ~has_head)
    return (await session.execute(query)).scalar_one()


async def create_index(
    session: AsyncSession, user: User, choice: EmbeddingChoice, dimension: int, status: str
) -> SearchIndex:
    """A new index version for the user. A concurrent first store may win the race:
    then the index it created is returned instead."""
    latest = (
        await session.execute(
            select(func.max(SearchIndex.version)).where(SearchIndex.user_id == user.id)
        )
    ).scalar_one()
    index = SearchIndex(
        user_id=user.id,
        version=(latest or 0) + 1,
        embedding_provider=choice.provider_id,
        embedding_model=choice.model,
        dimension=dimension,
        requested_dimensions=choice.dimensions,
        status=status,
    )
    try:
        async with session.begin_nested():
            session.add(index)
    except IntegrityError:
        existing = await index_with_status(session, user.id, status)
        if existing is None:
            raise
        return existing
    return index


def choice_of(index: SearchIndex) -> EmbeddingChoice:
    """The model an index was built with, asked for vectors of the same size."""
    return EmbeddingChoice(
        index.embedding_provider, index.embedding_model, index.requested_dimensions
    )


async def write_entries(
    session: AsyncSession,
    index: SearchIndex,
    items: list[tuple[uuid.UUID, list[Piece]]],
    vectors: list[list[float]],
) -> None:
    """Write these pieces' entries in the index, replacing the same chunks' old ones."""
    for thought_id, thought_pieces_ in items:
        await session.execute(
            delete(ThoughtEmbedding).where(
                ThoughtEmbedding.index_id == index.id,
                ThoughtEmbedding.thought_id == thought_id,
                ThoughtEmbedding.chunk.in_([piece.chunk for piece in thought_pieces_]),
            )
        )
    position = 0
    for thought_id, thought_pieces_ in items:
        for piece in thought_pieces_:
            session.add(
                ThoughtEmbedding(
                    index_id=index.id,
                    thought_id=thought_id,
                    chunk=piece.chunk,
                    start_char=piece.start_char,
                    end_char=piece.end_char,
                    embedding=vectors[position],
                )
            )
            position += 1


@dataclass
class EmbedOutcome:
    """What one embeddings call produced for the texts that were not thoughts."""

    index: SearchIndex | None
    extra_vectors: list[list[float]] = field(default_factory=list)
    error: ApiError | None = None


async def embed_for_index(
    session: AsyncSession,
    user: User,
    index: SearchIndex | None,
    items: list[tuple[uuid.UUID, list[Piece]]],
    *,
    settings: Settings,
    extra_texts: list[str] | None = None,
    create_status: str = ACTIVE,
    add_first: list[object] | None = None,
    conversation_id: uuid.UUID | None = None,
    http_client: httpx2.AsyncClient | None = None,
    max_retries: int = 0,
) -> EmbedOutcome:
    """Embed the extra texts and the thoughts' pieces in one call, and write the entries.

    Without an index, one is created with `create_status` from the resolver's
    choice and the first vector's dimension. A provider error or a vector of
    the wrong dimension writes nothing and is returned, not raised: the
    thoughts stay without entries until a later call fills them in.
    `add_first` holds new rows the entries refer to, such as the thought
    being stored; they are added before the entries. The caller adds them
    itself when the call fails, and commits.
    """
    extra = list(extra_texts or [])
    texts = extra + [piece.text for _, thought_pieces_ in items for piece in thought_pieces_]
    if not texts:
        return EmbedOutcome(index=index)
    choice = choice_of(index) if index is not None else resolve_embedding_model(user, settings)
    try:
        vectors = await embed_texts(
            session,
            user,
            choice.provider_id,
            choice.model,
            texts,
            settings=settings,
            dimensions=choice.dimensions,
            conversation_id=conversation_id,
            http_client=http_client,
            max_retries=max_retries,
        )
    except ApiError as exc:
        logger.info("Embedding for user %s failed: %s", user.id, exc.code)
        return EmbedOutcome(index=index, error=exc)
    dimension = len(vectors[0])
    if index is None:
        index = await create_index(session, user, choice, dimension, create_status)
    if dimension != index.dimension or choice.model != index.embedding_model:
        logger.warning(
            "Search index %s expects %s with %s dimensions, got %s: it needs a rebuild",
            index.id,
            index.embedding_model,
            index.dimension,
            dimension,
        )
        return EmbedOutcome(
            index=index,
            error=embedding_mismatch(f"{index.embedding_model}, {index.dimension} dimensions"),
        )
    session.add_all(add_first or [])
    await write_entries(session, index, items, vectors[len(extra) :])
    return EmbedOutcome(index=index, extra_vectors=vectors[: len(extra)])
