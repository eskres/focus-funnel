"""Storing, updating, and deleting thoughts (thought-storage task 5.1)."""

import uuid

import pytest
from sqlalchemy import func, select, text

from app.errors import ApiError
from app.models import SearchIndex, Thought, ThoughtEmbedding
from app.thoughts.store import delete_thought, get_thought, store_thought, update_thought
from tests.chat_helpers import FakeLLM, MODEL_LIST, api_error, run_db, save_key, user_id_for
from tests.thought_helpers import EMBED_MODEL, models_with_embedding, run_as

pytestmark = pytest.mark.postgres

LONG_RAW = "\n\n".join(
    f"Paragraph {n}. The flat near Alfama was cheaper than the hotel. " * 6 for n in range(4)
)


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def alice_id(client, alice, fake):
    save_key(client, alice)
    fake.embed_requests.clear()
    return user_id_for(client, alice)


@pytest.fixture
def bob_id(client, bob, fake):
    save_key(client, bob, key="nb-bob-key-2222")
    fake.embed_requests.clear()
    return user_id_for(client, bob)


def store(url, user_id, fake, **fields):
    async def work(session, user, settings, http_client):
        fields.setdefault("title", "Oat milk")
        fields.setdefault("summary", "Buy oat milk on the way home.")
        return await store_thought(session, user, settings=settings, http_client=http_client, **fields)

    return run_as(url, user_id, fake, work)


def update(url, user_id, fake, thought_id, **fields):
    async def work(session, user, settings, http_client):
        return await update_thought(
            session, user, thought_id, settings=settings, http_client=http_client, **fields
        )

    return run_as(url, user_id, fake, work)


def entries(url, thought_id) -> dict[str, list[int]]:
    """The chunks each index holds for a thought, by index status and model."""

    async def work(session):
        rows = await session.execute(
            select(SearchIndex.status, SearchIndex.embedding_model, ThoughtEmbedding.chunk)
            .join(SearchIndex, SearchIndex.id == ThoughtEmbedding.index_id)
            .where(ThoughtEmbedding.thought_id == thought_id)
            .order_by(ThoughtEmbedding.chunk)
        )
        found: dict[str, list[int]] = {}
        for status, model, chunk in rows:
            found.setdefault(f"{status}:{model}", []).append(chunk)
        return found

    return run_db(url, work)


def indexes(url, user_id) -> list[SearchIndex]:
    async def work(session):
        query = select(SearchIndex).where(SearchIndex.user_id == uuid.UUID(user_id))
        return list((await session.execute(query.order_by(SearchIndex.version))).scalars())

    return run_db(url, work)


def found_by_words(url, user_id, words: str) -> list[str]:
    async def work(session):
        rows = await session.execute(
            select(Thought.title).where(
                Thought.user_id == uuid.UUID(user_id),
                Thought.search_tsv.op("@@")(func.plainto_tsquery(text("'english'::regconfig"), words)),
            )
        )
        return list(rows.scalars())

    return run_db(url, work)


def head_texts(fake) -> list[str]:
    return [text for body in fake.embed_requests for text in body["input"]]


def test_fields_round_trip(test_database_url, fake, alice_id):
    outcome = store(
        test_database_url,
        alice_id,
        fake,
        tags=["groceries", "errands"],
        raw_text="From the shop on the corner.",
        category="to-do",
    )
    assert outcome.embedded

    async def work(session, user, settings, http_client):
        return await get_thought(session, user, outcome.thought.id)

    thought = run_as(test_database_url, alice_id, fake, work)
    assert (thought.title, thought.summary, thought.tags) == (
        "Oat milk",
        "Buy oat milk on the way home.",
        ["groceries", "errands"],
    )
    assert (thought.raw_text, thought.category) == ("From the shop on the corner.", "to-do")
    assert str(thought.user_id) == alice_id
    assert thought.created_at is not None and thought.updated_at is not None


@pytest.mark.parametrize(
    "fields, field",
    [
        ({"title": "  "}, "title"),
        ({"summary": " \n "}, "summary"),
        ({"title": "x" * 201}, "title"),
        ({"summary": "x" * 4001}, "summary"),
        ({"raw_text": "x" * 20001}, "raw_text"),
        ({"tags": [f"t{n}" for n in range(21)]}, "tags"),
        ({"tags": ["x" * 51]}, "tags"),
        ({"tags": "milk"}, "tags"),
    ],
)
def test_invalid_fields_are_refused_naming_the_field(test_database_url, fake, alice_id, fields, field):
    with pytest.raises(ApiError) as caught:
        store(test_database_url, alice_id, fake, **fields)
    assert caught.value.code == "validation_error"
    assert caught.value.message.startswith(f"{field}:")
    assert found_by_words(test_database_url, alice_id, "oat") == []
    assert fake.embed_requests == []


def test_tags_are_cleaned(test_database_url, fake, alice_id):
    outcome = store(test_database_url, alice_id, fake, tags=[" Milk", "milk", "", "Two  Words"])
    assert outcome.thought.tags == ["milk", "two words"]


def test_another_users_thought_is_treated_as_missing(test_database_url, fake, alice_id, bob_id):
    thought_id = store(test_database_url, bob_id, fake).thought.id

    async def get(session, user, settings, http_client):
        return await get_thought(session, user, thought_id)

    async def delete(session, user, settings, http_client):
        return await delete_thought(session, user, thought_id)

    for attempt in (
        lambda: run_as(test_database_url, alice_id, fake, get),
        lambda: update(test_database_url, alice_id, fake, thought_id, title="Mine now"),
        lambda: run_as(test_database_url, alice_id, fake, delete),
    ):
        with pytest.raises(ApiError) as caught:
            attempt()
        assert (caught.value.status_code, caught.value.code) == (404, "not_found")
    assert run_as(test_database_url, bob_id, fake, get).title == "Oat milk"


def test_first_store_creates_an_active_index(test_database_url, fake, alice_id):
    store(test_database_url, alice_id, fake)
    [index] = indexes(test_database_url, alice_id)
    assert (index.status, index.version) == ("active", 1)
    assert (index.embedding_provider, index.embedding_model) == ("nebius", EMBED_MODEL)
    assert index.dimension == len(fake.embedder("anything"))


def test_long_raw_text_is_embedded_in_chunks(test_database_url, fake, alice_id):
    outcome = store(test_database_url, alice_id, fake, raw_text=LONG_RAW)
    chunks = entries(test_database_url, outcome.thought.id)[f"active:{EMBED_MODEL}"]
    assert chunks[0] == 0 and len(chunks) >= 2


@pytest.mark.parametrize("failure", [api_error(500), api_error(429), api_error(401)])
def test_provider_failure_still_stores_a_thought_found_by_words(
    test_database_url, fake, alice_id, failure
):
    fake.embed_replies.append(failure)
    outcome = store(test_database_url, alice_id, fake)
    assert not outcome.embedded and outcome.error is not None
    assert entries(test_database_url, outcome.thought.id) == {}
    assert found_by_words(test_database_url, alice_id, "oat") == ["Oat milk"]


def test_no_key_still_stores_without_a_provider_call(client, test_database_url, fake, alice):
    user_id = user_id_for(client, alice)
    outcome = store(test_database_url, user_id, fake)
    assert outcome.error.code == "provider_key_missing"
    assert fake.embed_requests == []
    assert found_by_words(test_database_url, user_id, "milk") == ["Oat milk"]


def test_next_call_fills_in_missing_embeddings_in_the_same_call(test_database_url, fake, alice_id):
    fake.embed_replies.append(api_error(503))
    first = store(test_database_url, alice_id, fake, title="Dentist", summary="Book the dentist.")
    fake.embed_requests.clear()

    second = store(test_database_url, alice_id, fake)

    assert len(fake.embed_requests) == 1
    assert any(text.startswith("Dentist") for text in head_texts(fake))
    assert entries(test_database_url, first.thought.id) == {f"active:{EMBED_MODEL}": [0]}
    assert entries(test_database_url, second.thought.id) == {f"active:{EMBED_MODEL}": [0]}


def test_changed_summary_replaces_the_entries(test_database_url, fake, alice_id):
    thought_id = store(test_database_url, alice_id, fake, raw_text=LONG_RAW).thought.id
    fake.embed_requests.clear()

    outcome = update(test_database_url, alice_id, fake, thought_id, summary="Book the dentist.", raw_text=None)

    assert outcome.embedded
    assert entries(test_database_url, thought_id) == {f"active:{EMBED_MODEL}": [0]}
    assert head_texts(fake) == ["Oat milk\nBook the dentist."]
    assert found_by_words(test_database_url, alice_id, "dentist") == ["Oat milk"]
    assert found_by_words(test_database_url, alice_id, "home") == []


def test_changed_tags_replace_only_the_head(test_database_url, fake, alice_id):
    thought_id = store(test_database_url, alice_id, fake, raw_text=LONG_RAW).thought.id
    before = entries(test_database_url, thought_id)
    fake.embed_requests.clear()

    update(test_database_url, alice_id, fake, thought_id, tags=["groceries"])

    assert head_texts(fake) == ["Oat milk\n#groceries\nBuy oat milk on the way home."]
    assert entries(test_database_url, thought_id) == before
    assert found_by_words(test_database_url, alice_id, "groceries") == ["Oat milk"]


def test_changed_category_makes_no_embedding_call(test_database_url, fake, alice_id):
    thought_id = store(test_database_url, alice_id, fake).thought.id
    fake.embed_requests.clear()
    outcome = update(test_database_url, alice_id, fake, thought_id, category="errand")
    assert outcome.thought.category == "errand"
    assert fake.embed_requests == []


def test_update_while_the_provider_is_down_drops_the_old_entries(test_database_url, fake, alice_id):
    thought_id = store(test_database_url, alice_id, fake).thought.id
    fake.embed_replies.append(api_error(502))
    outcome = update(test_database_url, alice_id, fake, thought_id, summary="Book the dentist.")
    assert not outcome.embedded
    assert entries(test_database_url, thought_id) == {}
    assert found_by_words(test_database_url, alice_id, "dentist") == ["Oat milk"]


def test_store_during_a_rebuild_embeds_for_both_indexes(test_database_url, fake, alice_id):
    store(test_database_url, alice_id, fake, title="First", summary="The first thought.")

    async def start_rebuild(session):
        session.add(
            SearchIndex(
                user_id=uuid.UUID(alice_id),
                version=2,
                embedding_provider="nebius",
                embedding_model="vendor/embed-model-2",
                dimension=len(fake.embedder("x")),
                status="building",
            )
        )
        await session.commit()

    run_db(test_database_url, start_rebuild)
    fake.embed_requests.clear()

    outcome = store(test_database_url, alice_id, fake)

    assert [body["model"] for body in fake.embed_requests] == [EMBED_MODEL, "vendor/embed-model-2"]
    assert entries(test_database_url, outcome.thought.id) == {
        f"active:{EMBED_MODEL}": [0],
        "building:vendor/embed-model-2": [0],
    }


def test_delete_removes_the_thought_and_its_entries(test_database_url, fake, alice_id):
    thought_id = store(test_database_url, alice_id, fake, raw_text=LONG_RAW).thought.id

    async def delete(session, user, settings, http_client):
        await delete_thought(session, user, thought_id)

    run_as(test_database_url, alice_id, fake, delete)
    assert entries(test_database_url, thought_id) == {}
    assert found_by_words(test_database_url, alice_id, "oat") == []


def test_the_index_keeps_asking_for_its_vector_size(test_database_url, fake, alice_id, settings_env):
    from app.config import get_settings

    settings_env.setenv("EMBEDDING_DIMENSIONS", "256")
    get_settings.cache_clear()
    store(test_database_url, alice_id, fake)
    [index] = indexes(test_database_url, alice_id)
    assert index.requested_dimensions == 256

    settings_env.delenv("EMBEDDING_DIMENSIONS")
    get_settings.cache_clear()
    fake.embed_requests.clear()
    store(test_database_url, alice_id, fake, title="Dentist", summary="Book the dentist.")

    assert [body.get("dimensions") for body in fake.embed_requests] == [256]
