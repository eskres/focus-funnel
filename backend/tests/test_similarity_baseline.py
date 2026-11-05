"""Each index's similarity baseline (thought-appending task 3.2).

Postgres computes the percentiles from stored head entries, so these run on
Postgres with an index seeded directly with known vectors.
"""

import asyncio
import math
import random
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

from app import reembed
from app.chat.config import SimilarConfig, get_chat_config
from app.chat.similar import check_parts
from app.chat.tools import ProposalPart
from app.config import get_settings
from app.models import SearchIndex, Thought, ThoughtEmbedding
from app.thoughts import baseline
from app.thoughts.baseline import (
    MAX_PAIRS,
    cutoffs,
    measure_baseline,
    pair_count,
)
from app.thoughts.indexing import ACTIVE
from app.thoughts.store import store_thought
from tests.chat_helpers import MODEL_LIST, FakeLLM, run_db, save_key, user_id_for
from tests.thought_helpers import EMBED_MODEL, models_with_embedding, run_as

pytestmark = pytest.mark.postgres

NO_RULE = "acme/brand-new-embedder"
DIMENSION = 70  # concept_embedder's, so a store can add to a seeded index
SMALL = SimilarConfig(min_thoughts=5)


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def alice_id(client, alice, fake):
    save_key(client, alice)
    return user_id_for(client, alice)


def seed_index(url, user_id, count: int, *, seed: int = 7, **fields) -> uuid.UUID:
    """An active index with `count` thoughts, each with a random head entry
    and a raw-text entry the baseline must ignore."""
    rng = random.Random(seed)

    def vector() -> list[float]:
        return [rng.uniform(-0.2, 1.0) for _ in range(DIMENSION)]

    async def work(session):
        user = uuid.UUID(str(user_id))
        index = SearchIndex(
            user_id=user,
            version=1,
            embedding_provider=get_settings().embedding_provider,
            embedding_model=EMBED_MODEL,
            dimension=DIMENSION,
            status=ACTIVE,
            **fields,
        )
        session.add(index)
        await session.flush()
        for number in range(count):
            thought = Thought(user_id=user, title=f"Thought {number}", summary="A summary.", tags=[])
            session.add(thought)
            await session.flush()
            session.add(ThoughtEmbedding(index_id=index.id, thought_id=thought.id, chunk=0, embedding=vector()))
            session.add(ThoughtEmbedding(index_id=index.id, thought_id=thought.id, chunk=1, embedding=vector()))
        await session.commit()
        return index.id

    return run_db(url, work)


def stored_heads(url, index_id) -> list[list[float]]:
    async def work(session):
        rows = await session.execute(
            select(ThoughtEmbedding.embedding).where(
                ThoughtEmbedding.index_id == index_id, ThoughtEmbedding.chunk == 0
            )
        )
        return [[float(x) for x in value] for value in rows.scalars()]

    return run_db(url, work)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def percentile(values: list[float], share: float) -> float:
    """percentile_cont: linear interpolation between the closest ranks."""
    ordered = sorted(values)
    position = share * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def direct(url, index_id) -> tuple[float, float]:
    heads = stored_heads(url, index_id)
    similarities = [
        cosine(heads[i], heads[j]) for i in range(len(heads)) for j in range(i + 1, len(heads))
    ]
    return percentile(similarities, 0.95), percentile(similarities, 0.99)


def index_row(url, index_id) -> SearchIndex:
    return run_db(url, lambda session: session.get(SearchIndex, index_id))


def measure(url, user_id, fake, index_id, config=SMALL) -> bool:
    async def work(session, user, settings, http_client):
        index = await session.get(SearchIndex, index_id)
        return await measure_baseline(session, user, index, config=config)

    return run_as(url, user_id, fake, work)


def store(url, user_id, fake, title="Oat milk", summary="Buy oat milk."):
    async def work(session, user, settings, http_client):
        outcome = await store_thought(
            session, user, title=title, summary=summary, settings=settings, http_client=http_client
        )
        return outcome.thought.id

    return run_as(url, user_id, fake, work)


UNRELATED = [
    ("Oat milk", "Buy oat milk on the way home."),
    ("Dentist check-up", "Book a dentist appointment for the yearly check-up."),
    ("Lisbon trip", "Plan the Lisbon trip in May with Ana."),
    ("Piano lessons", "Ask the music school about evening piano lessons."),
    ("Tax return", "Gather receipts before filing the tax return."),
]


def small_baseline(monkeypatch, min_thoughts: int) -> None:
    """The shipped settings, with a smaller minimum, for the store and the rebuild."""
    config = get_chat_config()
    similar = replace(config.filing.similar, min_thoughts=min_thoughts)
    patched = replace(config, filing=replace(config.filing, similar=similar))
    monkeypatch.setattr(baseline, "get_chat_config", lambda: patched)


def test_the_percentiles_match_a_direct_calculation(test_database_url, fake, alice_id):
    index_id = seed_index(test_database_url, alice_id, 40)
    assert pair_count(40) <= MAX_PAIRS  # every pair is compared, so the result is exact
    fake.embed_requests.clear()

    assert measure(test_database_url, alice_id, fake, index_id)

    row = index_row(test_database_url, index_id)
    p95, p99 = direct(test_database_url, index_id)
    assert row.similarity_p95 == pytest.approx(p95, abs=1e-4)
    assert row.similarity_p99 == pytest.approx(p99, abs=1e-4)
    assert row.similarity_p95 < row.similarity_p99
    assert row.baseline_thoughts == 40
    # Measured from stored vectors only.
    assert fake.embed_requests == []


def test_past_2000_pairs_a_random_sample_comes_close(test_database_url, fake, alice_id):
    index_id = seed_index(test_database_url, alice_id, 90)
    assert pair_count(90) > MAX_PAIRS
    fake.embed_requests.clear()

    assert measure(test_database_url, alice_id, fake, index_id)

    row = index_row(test_database_url, index_id)
    p95, p99 = direct(test_database_url, index_id)
    assert row.similarity_p95 == pytest.approx(p95, abs=0.03)
    assert row.similarity_p99 == pytest.approx(p99, abs=0.05)
    assert row.baseline_thoughts == 90
    assert fake.embed_requests == []


def test_below_the_minimum_no_baseline_is_measured(test_database_url, fake, alice_id):
    index_id = seed_index(test_database_url, alice_id, 4)

    assert not measure(test_database_url, alice_id, fake, index_id)

    row = index_row(test_database_url, index_id)
    assert (row.similarity_p95, row.similarity_p99, row.baseline_thoughts) == (None, None, None)


def test_growth_measures_again_at_one_and_a_half_times(
    test_database_url, fake, alice_id, monkeypatch
):
    small_baseline(monkeypatch, 5)
    index_id = seed_index(test_database_url, alice_id, 10)
    assert measure(test_database_url, alice_id, fake, index_id)
    first = index_row(test_database_url, index_id)
    assert first.baseline_thoughts == 10

    for number in range(4):
        store(test_database_url, alice_id, fake, f"Oat milk {number}")
    # 14 thoughts: below 15, the baseline stays.
    assert index_row(test_database_url, index_id).baseline_thoughts == 10

    store(test_database_url, alice_id, fake, "Oat milk 4")

    grown = index_row(test_database_url, index_id)
    assert grown.baseline_thoughts == 15
    assert grown.similarity_p95 != first.similarity_p95
    assert grown.similarity_p95 == pytest.approx(direct(test_database_url, index_id)[0], abs=1e-4)


def test_a_store_measures_the_first_baseline_once_there_are_enough_thoughts(
    test_database_url, fake, alice_id, monkeypatch
):
    small_baseline(monkeypatch, 5)
    for number in range(4):
        store(test_database_url, alice_id, fake, f"Oat milk {number}")
    [index] = run_db(test_database_url, lambda s: _indexes(s, alice_id))
    assert index.baseline_thoughts is None

    store(test_database_url, alice_id, fake, "Dentist")

    measured = index_row(test_database_url, index.id)
    assert measured.baseline_thoughts == 5 and measured.similarity_p99 is not None


async def _indexes(session, user_id):
    query = select(SearchIndex).where(SearchIndex.user_id == uuid.UUID(str(user_id)))
    return list((await session.execute(query)).scalars())


def test_a_failure_keeps_the_old_baseline(test_database_url, fake, alice_id, monkeypatch, caplog):
    small_baseline(monkeypatch, 5)
    index_id = seed_index(
        test_database_url, alice_id, 10, similarity_p95=0.3, similarity_p99=0.5, baseline_thoughts=6
    )

    async def broken(session, index_id, heads):
        await session.execute(select(1).where(ThoughtEmbedding.chunk == "not a number"))

    monkeypatch.setattr(baseline, "percentiles", broken)

    assert not measure(test_database_url, alice_id, fake, index_id)
    # A store that makes the baseline due still stores, and keeps the old one.
    thought_id = store(test_database_url, alice_id, fake, "Oat milk")

    row = index_row(test_database_url, index_id)
    assert (row.similarity_p95, row.similarity_p99, row.baseline_thoughts) == (0.3, 0.5, 6)
    assert run_db(test_database_url, lambda s: s.get(Thought, thought_id)).title == "Oat milk"
    assert "Could not measure the similarity baseline" in caplog.text


def test_a_rebuild_measures_the_new_index_as_it_becomes_active(
    test_database_url, fake, alice_id, settings_env, monkeypatch
):
    small_baseline(monkeypatch, 5)
    url = test_database_url
    # Unrelated thoughts, so the baseline measures a typical pair.
    for title, summary in UNRELATED:
        store(url, alice_id, fake, title, summary)
    # A model that no chat.yaml rule names.
    assert get_chat_config().search.min_similarity_for(NO_RULE) == 0.35
    settings_env.setenv("EMBEDDING_MODEL", NO_RULE)
    get_settings.cache_clear()
    fake.embed_requests.clear()

    assert asyncio.run(reembed.main(["--user", str(alice_id)], http_client=fake.http_client())) == 0

    [new] = [i for i in run_db(url, lambda s: _indexes(s, alice_id)) if i.status == ACTIVE]
    assert new.embedding_model == NO_RULE
    assert new.baseline_thoughts == 5
    p95, p99 = direct(url, new.id)
    assert new.similarity_p95 == pytest.approx(p95, abs=1e-4)
    assert new.similarity_p99 == pytest.approx(p99, abs=1e-4)
    # The rebuild's embedding calls are for the thoughts; none for the baseline.
    assert sum(len(body["input"]) for body in fake.embed_requests) == 5

    # Its cut-offs come from the baseline, and the check works with them.
    limits = cutoffs(new, get_chat_config())
    assert limits.candidate == pytest.approx(max(p95 + 0.02, 0.25))
    assert limits.strong == pytest.approx(max(p99 + 0.02, 0.25))
    assert 0 < limits.candidate <= limits.strong < 1
    fake.embed_requests.clear()

    async def work(session, user, settings, http_client):
        return await check_parts(
            session,
            user,
            [ProposalPart(title="Oat milk", summary="Buy oat milk.", tags=[], category="task")],
            None,
            config=get_chat_config(),
            settings=settings,
            http_client=http_client,
        )

    check = run_as(url, alice_id, fake, work)
    titles = [candidate.thought.title for candidate in check.parts[0].candidates]
    assert titles and all(title.startswith("Oat milk") for title in titles)
    assert fake.embed_requests[0]["model"] == NO_RULE


def test_cut_offs_without_a_baseline_and_with_the_floor():
    config = get_chat_config()
    index = SearchIndex(embedding_model=NO_RULE)
    assert (cutoffs(index, config).candidate, cutoffs(index, config).strong) == pytest.approx(
        (0.25, 0.35)
    )
    # A baseline far below the search cut-off is held at the floor.
    index.similarity_p95, index.similarity_p99 = 0.05, 0.1
    assert (cutoffs(index, config).candidate, cutoffs(index, config).strong) == pytest.approx(
        (0.25, 0.25)
    )
    index.similarity_p95, index.similarity_p99 = 0.6, 0.8
    assert (cutoffs(index, config).candidate, cutoffs(index, config).strong) == pytest.approx(
        (0.62, 0.82)
    )
    # A chat.yaml rule still sets the floor for its model.
    qwen = SearchIndex(embedding_model="Qwen/Qwen3-Embedding-8B")
    assert (cutoffs(qwen, config).candidate, cutoffs(qwen, config).strong) == pytest.approx(
        (0.38, 0.48)
    )
