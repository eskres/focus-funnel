"""A stand-in embedding model for thought tests.

concept_embedder maps each text to counts of concept words, one dimension
per concept, so texts that share a concept are close and texts that share
none are far apart. The last dimension is a small constant, so no vector is
all zeros.
"""

import re
from collections.abc import Callable, Iterable

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


def words(text: str) -> list[str]:
    return re.findall(r"[\w-]+", text.lower())


def concept_embedder(concepts: Iterable[set[str]] = DEFAULT_CONCEPTS) -> Embedder:
    concept_list = [set(concept) for concept in concepts]

    def embed(text: str) -> list[float]:
        tokens = words(text)
        vector = [float(sum(token in concept for token in tokens)) for concept in concept_list]
        return [*vector, 0.05]

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
