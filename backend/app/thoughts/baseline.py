"""Each search index's similarity baseline (thought-appending design decision 5).

The baseline is the 95th and 99th percentile of cosine similarity between
the head entries (chunk 0) of random pairs of the user's thoughts in one
index. Postgres computes it from the stored vectors, with no embedding call.
The similar-thought check sets its cut-offs from it, so the check works with
any embedding model, including one `chat.yaml` has no rule for.

It is measured when an index becomes active (`app.reembed`), and again after
a store once the user's thought count reaches 1.5 times the count it was
last measured at. A user with fewer than `filing.similar.min_thoughts`
thoughts in the index gets no baseline. A failure is logged and keeps the
old baseline: a store never fails for it.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ChatConfig, SimilarConfig, get_chat_config
from app.models import SearchIndex, Thought, ThoughtEmbedding, User
from app.thoughts.indexing import ACTIVE, index_with_status

logger = logging.getLogger(__name__)

# At most this many pairs are compared. Up to it, every pair is, so the
# result is exact; past it, this many random pairs are drawn.
MAX_PAIRS = 2_000
# The baseline is measured again once the user has this many times the
# thoughts it was measured with.
GROWTH = 1.5

_HEADS = """
heads AS (
    SELECT thought_id, embedding, row_number() OVER (ORDER BY thought_id) - 1 AS n
    FROM thought_embeddings
    WHERE index_id = :index_id AND chunk = 0
)"""

_PERCENTILES = (
    "percentile_cont(ARRAY[0.95, 0.99]) WITHIN GROUP "
    "(ORDER BY 1 - (a.embedding <=> b.embedding))"
)

# Every pair once.
ALL_PAIRS = f"""
WITH {_HEADS}
SELECT {_PERCENTILES}
FROM heads a JOIN heads b ON a.n < b.n"""

# :pairs random pairs of two different heads, drawn by their row numbers.
SAMPLED_PAIRS = f"""
WITH {_HEADS},
draws AS (
    SELECT floor(random() * :count)::int AS i, floor(random() * (:count - 1))::int AS j
    FROM generate_series(1, :pairs)
),
pairs AS (
    SELECT i, CASE WHEN j >= i THEN j + 1 ELSE j END AS j FROM draws
)
SELECT {_PERCENTILES}
FROM pairs p JOIN heads a ON a.n = p.i JOIN heads b ON b.n = p.j"""


@dataclass(frozen=True)
class Cutoffs:
    """The similar-thought check's two similarity cut-offs."""

    # A thought at or above it is a candidate the model is told about.
    candidate: float
    # A thought at or above it is named on the card's "Similar" hint.
    strong: float


def cutoffs(index: SearchIndex, config: ChatConfig) -> Cutoffs:
    """The cut-offs for an index (design decision 5): from its baseline, and
    never below the search cut-off for its model minus `floor_delta`; without
    a baseline, that floor and the search cut-off. The search cut-off is the
    `chat.yaml` rule for the model, else the default, so a model with no rule
    still gets working cut-offs."""
    similar = config.filing.similar
    search = config.search.min_similarity_for(index.embedding_model)
    floor = search - similar.floor_delta
    if index.similarity_p95 is None or index.similarity_p99 is None:
        return Cutoffs(candidate=floor, strong=search)
    return Cutoffs(
        candidate=max(index.similarity_p95 + similar.candidate_margin, floor),
        strong=max(index.similarity_p99 + similar.strong_margin, floor),
    )


def pair_count(heads: int) -> int:
    return heads * (heads - 1) // 2


async def head_count(session: AsyncSession, index_id: uuid.UUID) -> int:
    query = select(func.count()).where(
        ThoughtEmbedding.index_id == index_id, ThoughtEmbedding.chunk == 0
    )
    return (await session.execute(query)).scalar_one()


async def thought_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    query = select(func.count()).select_from(Thought).where(Thought.user_id == user_id)
    return (await session.execute(query)).scalar_one()


async def percentiles(
    session: AsyncSession, index_id: uuid.UUID, heads: int
) -> tuple[float, float]:
    """The 95th and 99th percentile of similarity between head pairs: every
    pair while there are at most MAX_PAIRS, else MAX_PAIRS random ones."""
    if pair_count(heads) <= MAX_PAIRS:
        row = await session.execute(text(ALL_PAIRS), {"index_id": index_id})
    else:
        row = await session.execute(
            text(SAMPLED_PAIRS), {"index_id": index_id, "count": heads, "pairs": MAX_PAIRS}
        )
    p95, p99 = row.scalar_one()
    return float(p95), float(p99)


async def measure_baseline(
    session: AsyncSession,
    user: User,
    index: SearchIndex,
    *,
    config: SimilarConfig | None = None,
) -> bool:
    """Measure the index's baseline and commit it. Returns whether it was
    measured: not below `min_thoughts` thoughts with entries in the index.

    Never raises: a failure is logged, and the old baseline stays. Call it
    after the caller's own commit, never inside its transaction.
    """
    config = config or get_chat_config().filing.similar
    try:
        # A savepoint, so a failed query leaves the session usable and every
        # loaded row, the index's old baseline included, as it was.
        async with session.begin_nested():
            heads = await head_count(session, index.id)
            if heads < max(config.min_thoughts, 2):
                return False
            count = await thought_count(session, user.id)
            p95, p99 = await percentiles(session, index.id, heads)
            index.similarity_p95, index.similarity_p99 = p95, p99
            index.baseline_thoughts = count
    except Exception:
        logger.exception("Could not measure the similarity baseline of search index %s", index.id)
        return False
    try:
        await session.commit()
    except Exception:
        logger.exception("Could not store the similarity baseline of search index %s", index.id)
        # A failed commit leaves the session unusable until it rolls back:
        # the caller's next query (store_thought's refresh) would fail.
        try:
            await session.rollback()
        except Exception:
            logger.exception("Could not roll back after the similarity baseline")
        return False
    logger.info(
        "Search index %s baseline: p95 %.3f, p99 %.3f over %d thoughts", index.id, p95, p99, count
    )
    return True


def baseline_due(index: SearchIndex, count: int, config: SimilarConfig) -> bool:
    """Whether a store that leaves the user with `count` thoughts measures
    the active index's baseline: none yet, or the count grew 1.5 times."""
    if count < config.min_thoughts:
        return False
    return index.baseline_thoughts is None or count >= GROWTH * index.baseline_thoughts


async def measure_after_store(
    session: AsyncSession, user: User, *, config: SimilarConfig | None = None
) -> bool:
    """After a store's commit: measure the active index's baseline when it is
    due. Postgres only. Never raises."""
    if session.bind.dialect.name != "postgresql":
        return False
    config = config or get_chat_config().filing.similar
    try:
        async with session.begin_nested():
            index = await index_with_status(session, user.id, ACTIVE)
            count = await thought_count(session, user.id)
        if index is None or not baseline_due(index, count, config):
            return False
    except Exception:
        logger.exception("Could not check the similarity baseline of user %s", user.id)
        return False
    return await measure_baseline(session, user, index, config=config)
