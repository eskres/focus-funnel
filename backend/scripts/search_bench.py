"""Time the search SQL for a user with many thoughts (thought-storage task 6.6).

Seeds one user with --thoughts thoughts (a third with raw text of three
chunks) and random vectors of --dimension, then runs --searches searches with
random query vectors and a two-word query, and times the database part: the
ranking statement and loading the matched thoughts. The target in the spec is
a 95th percentile under 50 ms for 5,000 thoughts.

Run from backend/ against a Postgres with pgvector. The script creates a
scratch database next to the one in the URL and drops it afterwards:

  uv run python -m scripts.search_bench \\
      --database-url postgresql+asyncpg://focus_funnel:focus_funnel@localhost:55432/focus_funnel \\
      --dimension 1024
"""

import argparse
import asyncio
import math
import random
import statistics
import sys
import time
import uuid

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import load_chat_config
from app.models import SearchIndex, Thought, ThoughtEmbedding, User
from app.thoughts.search import rank
from app.thoughts.store import TS_CONFIG
from scripts.search_eval import eval_config, with_scratch_database

# A vocabulary the size of a personal notes collection, drawn with a Zipf-like
# skew so a few words are common and most are rare, as in real text.
VOCABULARY = [f"word{number:04d}" for number in range(4000)]
WEIGHTS = [1 / (rank + 1) for rank in range(len(VOCABULARY))]


def draw(rng: random.Random, count: int) -> list[str]:
    return rng.choices(VOCABULARY, weights=WEIGHTS, k=count)


def unit_vector(rng: random.Random, dimension: int) -> list[float]:
    values = [rng.gauss(0, 1) for _ in range(dimension)]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


def sentence(rng: random.Random, words: int) -> str:
    return " ".join(draw(rng, words)).capitalize() + "."


async def seed(session: AsyncSession, count: int, dimension: int, rng: random.Random):
    user = User(issuer="search-bench", subject=uuid.uuid4().hex)
    session.add(user)
    await session.flush()
    index = SearchIndex(
        user_id=user.id,
        version=1,
        embedding_provider="bench",
        embedding_model="bench",
        dimension=dimension,
        status="active",
    )
    session.add(index)
    await session.flush()
    thoughts, entries = [], []
    for number in range(count):
        thought_id = uuid.uuid4()
        with_raw = number % 3 == 0
        thoughts.append(
            {
                "id": thought_id,
                "user_id": user.id,
                "title": sentence(rng, 3),
                "summary": sentence(rng, 18),
                "raw_text": " ".join(sentence(rng, 20) for _ in range(20)) if with_raw else None,
                "tags": draw(rng, 2),
            }
        )
        for chunk in range(4 if with_raw else 1):
            entries.append(
                {
                    "id": uuid.uuid4(),
                    "index_id": index.id,
                    "thought_id": thought_id,
                    "chunk": chunk,
                    "embedding": unit_vector(rng, dimension),
                }
            )
    for start in range(0, len(thoughts), 1000):
        await session.execute(insert(Thought), thoughts[start : start + 1000])
    await session.execute(
        text(
            f"""UPDATE thoughts SET search_tsv =
                setweight(to_tsvector('{TS_CONFIG}', title), 'A')
                || setweight(to_tsvector('{TS_CONFIG}', array_to_string(tags, ' ')), 'A')
                || setweight(to_tsvector('{TS_CONFIG}', summary), 'B')
                || setweight(to_tsvector('{TS_CONFIG}', coalesce(raw_text, '')), 'C')
            WHERE user_id = :user_id"""
        ),
        {"user_id": user.id},
    )
    for start in range(0, len(entries), 500):
        await session.execute(insert(ThoughtEmbedding), entries[start : start + 500])
    await session.commit()
    await session.execute(text("ANALYZE"))
    return user, index, len(entries)


async def bench(session: AsyncSession, args) -> list[float]:
    rng = random.Random(args.seed)
    started = time.monotonic()
    user, index, entry_count = await seed(session, args.thoughts, args.dimension, rng)
    print(f"Seeded {args.thoughts} thoughts, {entry_count} entries in {time.monotonic() - started:.0f} s.")
    version = (await session.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))).scalar()
    server = (await session.execute(text("SHOW server_version"))).scalar()
    print(f"Postgres {server}, pgvector {version}.")
    config = eval_config(load_chat_config().search)
    timings = []
    for number in range(args.searches + 5):
        vector = unit_vector(rng, args.dimension)
        # Queries name content words: the 50 commonest words, which English
        # stop word removal would mostly drop, are left out.
        query = " ".join(rng.choice(VOCABULARY[50:]) for _ in range(2))
        started = time.perf_counter()
        await rank(session, user, query, index=index, query_vector=vector, config=config)
        elapsed = (time.perf_counter() - started) * 1000
        if number >= 5:  # the first few warm the caches
            timings.append(elapsed)
    return timings


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--thoughts", type=int, default=5000)
    parser.add_argument("--dimension", type=int, default=1024)
    parser.add_argument("--searches", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    timings = await with_scratch_database(args.database_url, lambda session: bench(session, args))
    ordered = sorted(timings)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    print(
        f"{len(timings)} searches, {args.dimension} dimensions: median {statistics.median(timings):.1f} ms, "
        f"95th percentile {p95:.1f} ms, max {ordered[-1]:.1f} ms. Target: 95th percentile under 50 ms: "
        f"{'pass' if p95 < 50 else 'fail'}."
    )
    return 0 if p95 < 50 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
