"""Embedding calls with the user's own key (thought-storage task 4.1)."""

import uuid
from decimal import Decimal

import httpx2
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.demo_keys import HeldKey, _held_keys
from app.errors import ApiError
from app.models import UsageEvent, User
from app.thoughts.embeddings import embed_texts
from tests.chat_helpers import FakeLLM, MODEL_LIST, api_error, run_db, save_key, user_id_for
from tests.thought_helpers import EMBED_MODEL, EMBED_PRICE, models_with_embedding


@pytest.fixture
def fake() -> FakeLLM:
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


def embed(url, user_id, fake, texts, **options):
    async def work(session):
        user = await session.get(User, uuid.UUID(user_id))
        return await embed_texts(
            session,
            user,
            options.pop("provider_id", "nebius"),
            options.pop("model", EMBED_MODEL),
            texts,
            settings=get_settings(),
            http_client=fake.http_client(),
            **options,
        )

    return run_db(url, work)


def embed_error(url, user_id, fake, texts=("a text",)) -> ApiError:
    with pytest.raises(ApiError) as caught:
        embed(url, user_id, fake, list(texts))
    return caught.value


def usage_events(url, user_id) -> list[UsageEvent]:
    async def work(session):
        query = select(UsageEvent).where(UsageEvent.user_id == uuid.UUID(user_id))
        return list((await session.execute(query)).scalars())

    return run_db(url, work)


def authorization(request: httpx2.Request) -> str:
    return request.headers["authorization"]


def test_uses_the_users_own_key(client, test_database_url, fake, alice, bob):
    save_key(client, alice, key="nb-alice-key-1111")
    save_key(client, bob, key="nb-bob-key-2222")
    fake.requests.clear()

    vectors = embed(test_database_url, user_id_for(client, alice), fake, ["buy oat milk"])

    assert len(vectors) == 1
    embed_calls = [r for r in fake.requests if r.url.path.endswith("/embeddings")]
    assert [authorization(r) for r in embed_calls] == ["Bearer nb-alice-key-1111"]


def test_demo_mode_uses_the_held_key(test_database_url, settings_env, fake):
    for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID"):
        settings_env.delenv(name)
    settings_env.setenv("AUTH_MODE", "demo")

    async def work(session):
        user = User(issuer="demo", subject=uuid.uuid4().hex)
        session.add(user)
        await session.commit()
        token = _held_keys.set({"nebius": HeldKey(key="nb-held-key-3333", expires_at=None)})
        try:
            return await embed_texts(
                session,
                user,
                "nebius",
                EMBED_MODEL,
                ["a text"],
                settings=get_settings(),
                http_client=fake.http_client(),
            )
        finally:
            _held_keys.reset(token)

    run_db(test_database_url, work)
    embed_calls = [r for r in fake.requests if r.url.path.endswith("/embeddings")]
    assert [authorization(r) for r in embed_calls] == ["Bearer nb-held-key-3333"]


def test_missing_key(client, test_database_url, fake, alice):
    error = embed_error(test_database_url, user_id_for(client, alice), fake)
    assert error.code == "provider_key_missing"


@pytest.mark.parametrize(
    "reply, code",
    [
        (api_error(401), "provider_key_rejected"),
        (api_error(403), "provider_key_rejected"),
        (api_error(429), "provider_rate_limited"),
        (api_error(500), "provider_unreachable"),
        (api_error(400, "input too long"), "provider_request_refused"),
        (api_error(404, "model not found"), "model_unavailable"),
    ],
)
def test_provider_errors_map_as_for_chat(client, test_database_url, fake, alice, reply, code):
    save_key(client, alice)
    fake.embed_replies.append(reply)
    assert embed_error(test_database_url, user_id_for(client, alice), fake).code == code


def test_connection_failure_is_unreachable(client, test_database_url, fake, alice):
    save_key(client, alice)

    def refuse(request):
        raise httpx2.ConnectError("refused", request=request)

    fake.embed_replies.append(refuse)
    assert embed_error(test_database_url, user_id_for(client, alice), fake).code == (
        "provider_unreachable"
    )


def test_texts_go_in_batches_of_64(client, test_database_url, fake, alice):
    save_key(client, alice)
    texts = [f"text number {n}" for n in range(130)]

    vectors = embed(test_database_url, user_id_for(client, alice), fake, texts)

    assert len(vectors) == 130
    assert [len(body["input"]) for body in fake.embed_requests] == [64, 64, 2]


def test_dimensions_are_sent_only_when_set(client, test_database_url, fake, alice):
    save_key(client, alice)
    user_id = user_id_for(client, alice)
    embed(test_database_url, user_id, fake, ["one"])
    embed(test_database_url, user_id, fake, ["two"], dimensions=256)
    assert "dimensions" not in fake.embed_requests[0]
    assert fake.embed_requests[1]["dimensions"] == 256


def test_unequal_vector_lengths_are_refused(client, test_database_url, fake, alice):
    save_key(client, alice)
    lengths = iter([3, 4])
    fake.embedder = lambda text: [0.1] * next(lengths)
    error = embed_error(test_database_url, user_id_for(client, alice), fake, ["a", "b"])
    assert error.code == "embedding_mismatch"


def test_one_usage_event_per_call_without_text(client, test_database_url, fake, alice):
    save_key(client, alice)
    user_id = user_id_for(client, alice)
    texts = ["buy oat milk"] * 70

    embed(test_database_url, user_id, fake, texts)

    events = usage_events(test_database_url, user_id)
    assert len(events) == 2
    assert {event.kind for event in events} == {"embed"}
    assert sorted(event.prompt_tokens for event in events) == [3 * 6, 3 * 64]
    assert all(event.completion_tokens is None for event in events)
    assert all(event.model == EMBED_MODEL and event.provider_id == "nebius" for event in events)
    event = max(events, key=lambda event: event.prompt_tokens)
    assert event.cost_usd == Decimal(EMBED_PRICE) * 3 * 64
    stored = " ".join(str(value) for event in events for value in vars(event).values())
    assert "oat milk" not in stored


def test_unpriced_model_records_unknown_cost(client, test_database_url, fake, alice):
    save_key(client, alice)
    user_id = user_id_for(client, alice)
    embed(test_database_url, user_id, fake, ["a"], model="vendor/unlisted-embedder")
    [event] = usage_events(test_database_url, user_id)
    assert event.prompt_tokens == 1 and event.cost_usd is None


def test_no_texts_make_no_call(client, test_database_url, fake, alice):
    save_key(client, alice)
    assert embed(test_database_url, user_id_for(client, alice), fake, []) == []
    assert fake.embed_requests == []
