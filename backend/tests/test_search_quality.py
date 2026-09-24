"""Search quality does not drop below the recorded baseline (thought-storage task 6.5).

tests/fixtures/search_eval/vectors.json holds the evaluation set's vectors
from one embedding model and the hybrid scores it reached, written by
`python -m scripts.search_eval --write-fixture`. This runs the same scoring
offline with the tuning in chat.yaml.
"""

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.chat.config import load_chat_config
from app.db import create_engine
from scripts.search_eval import eval_config, load_corpus, read_fixture, score

pytestmark = pytest.mark.postgres

MARGIN = 0.02


def hybrid_scores(url: str, config=None):
    vectors = read_fixture()

    async def run():
        engine = create_engine(url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                user, index, names = await load_corpus(session, vectors)
                chosen = config or eval_config(load_chat_config().search)
                return await score(session, user, index, names, vectors, chosen, "hybrid")
        finally:
            await engine.dispose()

    return vectors, asyncio.run(run())


def test_hybrid_search_keeps_its_baseline(test_database_url):
    vectors, scores = hybrid_scores(test_database_url)
    baseline = vectors.baseline
    assert scores.recall_at_5 >= baseline["recall_at_5"] - MARGIN, (scores.as_dict(), baseline)
    assert scores.mrr >= baseline["mrr"] - MARGIN, (scores.as_dict(), baseline)


def test_the_check_catches_a_threshold_set_far_too_high(test_database_url):
    base = eval_config(load_chat_config().search)
    strict = replace(base, min_similarity=0.99, similarity_rules=(), min_word_share=1.0)
    vectors, scores = hybrid_scores(test_database_url, strict)
    baseline = vectors.baseline
    assert (
        scores.recall_at_5 < baseline["recall_at_5"] - MARGIN
        or scores.mrr < baseline["mrr"] - MARGIN
    )
