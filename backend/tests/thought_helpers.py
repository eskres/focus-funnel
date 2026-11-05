"""A stand-in embedding model for thought tests.

concept_embedder maps each text to counts of concept words, one dimension
per concept, so texts that share a concept are close and texts that share
none are far apart. A lighter bag of hashed words follows, so texts with no
concept word still differ, and a small constant ends it, so no vector is all
zeros.
"""

import re
import zlib
from collections.abc import Callable, Iterable
from contextlib import contextmanager

EMBED_MODEL = "vendor/embed-model"
EMBED_PRICE = "0.00000002"

DEFAULT_CONCEPTS: list[set[str]] = [
    {"milk", "oat", "groceries", "grocery", "buy", "shopping", "food", "errands"},
    {"dentist", "teeth", "tooth", "check-up", "cleaning", "health"},
    {"lisbon", "travel", "trip", "flight", "flights", "alfama", "tram", "hotel", "weekend"},
    {"work", "plans", "roadmap", "meeting", "project", "priorities"},
    {"quantum", "physics", "lecture"},
]

Embedder = Callable[[str], list[float]]
HASH_BUCKETS = 64
HASH_WEIGHT = 0.2


def words(text: str) -> list[str]:
    return re.findall(r"[\w-]+", text.lower())


def concept_embedder(concepts: Iterable[set[str]] = DEFAULT_CONCEPTS) -> Embedder:
    concept_list = [set(concept) for concept in concepts]

    def embed(text: str) -> list[float]:
        tokens = words(text)
        vector = [float(sum(token in concept for token in tokens)) for concept in concept_list]
        buckets = [0.0] * HASH_BUCKETS
        for token in tokens:
            buckets[zlib.crc32(token.encode()) % HASH_BUCKETS] += HASH_WEIGHT
        return [*vector, *buckets, 0.05]

    return embed


def models_with_embedding(model_list: dict) -> dict:
    """A model list that also lists the stand-in embedding model with a price."""
    return {
        **model_list,
        "data": [
            *model_list["data"],
            {"id": EMBED_MODEL, "pricing": {"prompt": EMBED_PRICE, "completion": "0"}},
        ],
    }


def run_as(url: str, user_id, fake, work, **settings_overrides):
    """Run `await work(session, user, settings, http_client)` against the test database."""
    import uuid as uuid_module

    from app.config import get_settings
    from app.models import User
    from tests.chat_helpers import run_db

    async def main(session):
        user = await session.get(User, uuid_module.UUID(str(user_id)))
        return await work(session, user, get_settings(), fake.http_client())

    return run_db(url, main)


def entries(url, thought_id) -> dict[str, list[int]]:
    """The chunks each index holds for a thought, by index status and model."""
    import uuid as uuid_module

    from sqlalchemy import select

    from app.models import SearchIndex, ThoughtEmbedding
    from tests.chat_helpers import run_db

    async def work(session):
        rows = await session.execute(
            select(SearchIndex.status, SearchIndex.embedding_model, ThoughtEmbedding.chunk)
            .join(SearchIndex, SearchIndex.id == ThoughtEmbedding.index_id)
            .where(ThoughtEmbedding.thought_id == uuid_module.UUID(str(thought_id)))
            .order_by(ThoughtEmbedding.chunk)
        )
        found: dict[str, list[int]] = {}
        for status, model, chunk in rows:
            found.setdefault(f"{status}:{model}", []).append(chunk)
        return found

    return run_db(url, work)


def found_by_words(url, user_id, words: str) -> list[str]:
    """The titles of the user's thoughts that a word search for `words` finds."""
    import uuid as uuid_module

    from sqlalchemy import func, select, text

    from app.models import Thought
    from tests.chat_helpers import run_db

    async def work(session):
        rows = await session.execute(
            select(Thought.title).where(
                Thought.user_id == uuid_module.UUID(str(user_id)),
                Thought.search_tsv.op("@@")(func.plainto_tsquery(text("'english'::regconfig"), words)),
            )
        )
        return list(rows.scalars())

    return run_db(url, work)


def head_texts(fake) -> list[str]:
    """Every text the fake provider was asked to embed, in order."""
    return [text for body in fake.embed_requests for text in body["input"]]


@contextmanager
def counted_queries():
    """The SQL statements run while the block runs, from any engine."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", record)
