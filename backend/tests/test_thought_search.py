"""Hybrid thought search (thought-storage task 6.1)."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import update

from app.chat.config import InstructionRule, get_chat_config
from app.models import Thought
from app.thoughts.search import search_thoughts
from app.thoughts.store import store_thought
from tests.chat_helpers import FakeLLM, MODEL_LIST, api_error, run_db, save_key, user_id_for
from tests.thought_helpers import EMBED_MODEL, models_with_embedding, run_as

pytestmark = pytest.mark.postgres


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def alice_id(client, alice, fake):
    save_key(client, alice)
    return user_id_for(client, alice)


def store(url, user_id, fake, title, summary, **fields):
    async def work(session, user, settings, http_client):
        outcome = await store_thought(
            session,
            user,
            title=title,
            summary=summary,
            settings=settings,
            http_client=http_client,
            **fields,
        )
        return outcome.thought.id

    return run_as(url, user_id, fake, work)


def search(url, user_id, fake, query, **options):
    async def work(session, user, settings, http_client):
        return await search_thoughts(
            session, user, query, settings=settings, http_client=http_client, **options
        )

    return run_as(url, user_id, fake, work)


def titles(result) -> list[str]:
    return [hit.thought.title for hit in result.hits]


def set_created(url, thought_id, when: datetime):
    async def work(session):
        await session.execute(update(Thought).where(Thought.id == thought_id).values(created_at=when))
        await session.commit()

    run_db(url, work)


def seed(url, user_id, fake):
    store(url, user_id, fake, "Oat milk", "Buy oat milk on the way home.", tags=["groceries"])
    store(url, user_id, fake, "Dentist", "Book a check-up before October.", tags=["health"])
    store(url, user_id, fake, "Server invoice ACME-4471", "Pay the hosting invoice.", tags=["work"])
    store(url, user_id, fake, "Q4 plans", "Ship offline mode first.", tags=["work", "plans"])


def test_match_by_meaning(test_database_url, fake, alice_id):
    seed(test_database_url, alice_id, fake)
    result = search(test_database_url, alice_id, fake, "groceries")
    assert "Oat milk" in titles(result)
    assert result.words_only is None


def test_exact_code_ranks_first(test_database_url, fake, alice_id):
    seed(test_database_url, alice_id, fake)
    assert titles(search(test_database_url, alice_id, fake, "ACME-4471"))[0] == (
        "Server invoice ACME-4471"
    )


def test_detail_only_in_raw_text(test_database_url, fake, alice_id):
    seed(test_database_url, alice_id, fake)
    raw = ("We looked at hotels and flats. " * 30) + "The best one was in Lisbon near the river."
    store(test_database_url, alice_id, fake, "Autumn trip", "A long weekend away.", raw_text=raw)

    result = search(test_database_url, alice_id, fake, "Lisbon")

    [hit] = [hit for hit in result.hits if hit.thought.title == "Autumn trip"]
    assert "Lisbon" in hit.excerpt and len(hit.excerpt) <= 242
    assert all(hit.excerpt is None for hit in result.hits if hit.thought.title != "Autumn trip")


def test_nothing_relevant_gives_an_empty_result(test_database_url, fake, alice_id):
    store(test_database_url, alice_id, fake, "Oat milk", "Buy oat milk on the way home.")
    store(test_database_url, alice_id, fake, "Bread", "Buy groceries: bread and butter.")
    assert search(test_database_url, alice_id, fake, "quantum physics").hits == []


def test_result_limit(test_database_url, fake, alice_id):
    for n in range(12):
        store(test_database_url, alice_id, fake, f"Milk {n}", "Buy oat milk.")
    result = search(test_database_url, alice_id, fake, "milk")
    assert len(result.hits) == 8
    assert result.total == 12


def test_tag_filter(test_database_url, fake, alice_id):
    seed(test_database_url, alice_id, fake)
    result = search(test_database_url, alice_id, fake, "plans invoice", tags=["work"])
    assert titles(result) and all("work" in hit.thought.tags for hit in result.hits)


def test_tag_filter_takes_a_tag_as_the_result_shows_it(test_database_url, fake, alice_id):
    seed(test_database_url, alice_id, fake)
    result = search(test_database_url, alice_id, fake, "plans", tags=["#Plans"])
    assert titles(result) == ["Q4 plans"]


def test_tag_nobody_uses_makes_no_provider_call(test_database_url, fake, alice_id):
    seed(test_database_url, alice_id, fake)
    fake.embed_requests.clear()
    assert search(test_database_url, alice_id, fake, "plans", tags=["astronomy"]).hits == []
    assert fake.embed_requests == []


def test_date_filters(test_database_url, fake, alice_id):
    old = store(test_database_url, alice_id, fake, "Old milk", "Buy oat milk.")
    new = store(test_database_url, alice_id, fake, "New milk", "Buy oat milk again.")
    set_created(test_database_url, old, datetime(2026, 8, 20, tzinfo=UTC))
    set_created(test_database_url, new, datetime(2026, 9, 3, tzinfo=UTC))

    assert titles(search(test_database_url, alice_id, fake, "milk", since=date(2026, 9, 1))) == [
        "New milk"
    ]
    assert titles(search(test_database_url, alice_id, fake, "milk", until=date(2026, 8, 20))) == [
        "Old milk"
    ]


def test_newest_first(test_database_url, fake, alice_id):
    ids = [
        store(test_database_url, alice_id, fake, f"Milk {n}", "Buy oat milk " + "milk " * n)
        for n in range(3)
    ]
    for day, thought_id in zip((5, 1, 9), ids):
        set_created(test_database_url, thought_id, datetime(2026, 9, day, tzinfo=UTC))
    result = search(test_database_url, alice_id, fake, "milk", newest_first=True)
    assert titles(result) == ["Milk 2", "Milk 0", "Milk 1"]


def test_users_never_see_each_others_thoughts(client, test_database_url, fake, alice_id, bob):
    save_key(client, bob, key="nb-bob-key-2222")
    bob_id = user_id_for(client, bob)
    store(test_database_url, alice_id, fake, "Alice milk", "Buy oat milk.")
    store(test_database_url, bob_id, fake, "Bob milk", "Buy oat milk.")
    assert titles(search(test_database_url, alice_id, fake, "milk")) == ["Alice milk"]
    assert titles(search(test_database_url, bob_id, fake, "milk", tags=None)) == ["Bob milk"]


@pytest.mark.parametrize(
    "reply, code",
    [
        (api_error(500), "provider_unreachable"),
        (api_error(429), "provider_rate_limited"),
        (api_error(401), "provider_key_rejected"),
    ],
)
def test_words_only_when_the_provider_fails(test_database_url, fake, alice_id, reply, code):
    seed(test_database_url, alice_id, fake)
    fake.embed_replies.append(reply)
    result = search(test_database_url, alice_id, fake, "invoice")
    assert titles(result) == ["Server invoice ACME-4471"]
    assert result.words_only.code == code
    assert not result.rebuild_needed


def test_words_only_without_a_key(client, test_database_url, fake, bob):
    bob_id = user_id_for(client, bob)
    store(test_database_url, bob_id, fake, "Oat milk", "Buy oat milk on the way home.")
    result = search(test_database_url, bob_id, fake, "oat")
    assert titles(result) == ["Oat milk"]
    assert result.words_only.code == "provider_key_missing"
    assert "Nebius" in result.words_only.message


def test_no_thoughts_makes_no_provider_call(test_database_url, fake, alice_id):
    fake.embed_requests.clear()
    result = search(test_database_url, alice_id, fake, "anything")
    assert result.hits == [] and result.words_only is None
    assert fake.embed_requests == []


def test_changed_dimension_searches_by_words_and_asks_for_a_rebuild(test_database_url, fake, alice_id):
    seed(test_database_url, alice_id, fake)
    original = fake.embedder
    fake.embedder = lambda text: original(text) + [0.0, 0.0]
    result = search(test_database_url, alice_id, fake, "invoice")
    assert titles(result) == ["Server invoice ACME-4471"]
    assert result.words_only.code == "embedding_mismatch"
    assert result.rebuild_needed


def test_search_fills_in_missing_embeddings(test_database_url, fake, alice_id):
    fake.embed_replies.append(api_error(503))
    store(test_database_url, alice_id, fake, "Oat milk", "Buy oat milk on the way home.")
    fake.embed_requests.clear()

    result = search(test_database_url, alice_id, fake, "groceries")

    assert len(fake.embed_requests) == 1
    assert fake.embed_requests[0]["input"][0] == "groceries"
    assert titles(result) == ["Oat milk"] and result.hits[0].similarity is not None



def test_query_instruction_goes_before_the_query_only(test_database_url, fake, alice_id):
    fake.embed_replies.append(api_error(503))
    store(test_database_url, alice_id, fake, "Oat milk", "Buy oat milk on the way home.")
    fake.embed_requests.clear()
    config = replace(
        get_chat_config().search,
        query_instructions=(InstructionRule(match="vendor/embed-*", text="Instruct: find\nQuery:"),),
    )

    search(test_database_url, alice_id, fake, "groceries", config=config)

    texts = fake.embed_requests[0]["input"]
    assert texts[0] == "Instruct: find\nQuery:groceries"
    assert len(texts) > 1 and not any(text.startswith("Instruct") for text in texts[1:])
