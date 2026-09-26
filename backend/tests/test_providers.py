import httpx2
import openai
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.providers as providers
from app.config import Settings
from app.crypto import encrypt_secret
from app.db import create_engine
from app.errors import ApiError, ErrorCode
from app.models import Base, ProviderKey, User
from app.provider_config import ModelListCapabilities, ProviderCapabilities, ProviderPreset
from app.providers import (
    PLACEHOLDER_KEY,
    check_provider_key,
    client_for,
    load_api_key,
    map_provider_error,
)
from tests.conftest import FakeProvider, fail_with, status

BASE_URL = "https://provider.test/v1/"
MODELS_OK = {"object": "list", "data": []}


def make_provider(
    provider_id: str = "nebius",
    key_required: bool = True,
    label: str = "Test Provider",
    key_check_url: str | None = None,
) -> ProviderPreset:
    return ProviderPreset(
        id=provider_id,
        label=label,
        base_url=BASE_URL,
        key_url="https://provider.test/keys",
        notice="A notice.",
        key_required=key_required,
        key_check_url=key_check_url,
        capabilities=ProviderCapabilities(
            model_list=ModelListCapabilities(prices=True, context_length=True, features=True),
            stream_usage="final_chunk",
        ),
    )


@pytest.fixture
def provider() -> ProviderPreset:
    return make_provider()


@pytest.fixture
async def session():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def add_user(session, sub: str) -> User:
    user = User(issuer="test-issuer", subject=sub)
    session.add(user)
    await session.commit()
    return user


async def save_key(session, settings, user, provider, api_key, encrypt_for=None):
    secret = encrypt_secret(
        settings.key_encryption_key, (encrypt_for or user).id, provider.id, api_key
    )
    session.add(
        ProviderKey(
            user_id=user.id,
            provider_id=provider.id,
            ciphertext=secret.ciphertext,
            nonce=secret.nonce,
            key_version=secret.key_version,
            last4=api_key[-4:],
        )
    )
    await session.commit()


async def assert_raises_code(awaitable, code: str) -> ApiError:
    with pytest.raises(ApiError) as error:
        await awaitable
    assert error.value.code == code
    return error.value


# --- checking a key before saving ---


async def test_valid_key_passes(provider):
    fake = FakeProvider(status(200, MODELS_OK))
    await check_provider_key(provider, "nb-good", http_client=fake.http_client())

    assert len(fake.requests) == 1
    assert str(fake.requests[0].url) == f"{BASE_URL}models"
    assert fake.requests[0].headers["Authorization"] == "Bearer nb-good"


CHECK_URL = "https://provider.test/v1/auth/key"


async def test_key_check_url_is_called_instead_of_the_model_list():
    provider = make_provider(key_check_url=CHECK_URL)
    fake = FakeProvider(status(200, {"data": {}}))

    await check_provider_key(provider, "nb-good", http_client=fake.http_client())

    assert [str(r.url) for r in fake.requests] == [CHECK_URL]
    assert fake.requests[0].method == "GET"
    assert fake.requests[0].headers["Authorization"] == "Bearer nb-good"


@pytest.mark.parametrize("code", [401, 403])
async def test_key_check_url_rejection_means_invalid_key(code):
    provider = make_provider(key_check_url=CHECK_URL)
    fake = FakeProvider(status(code))
    error = await assert_raises_code(
        check_provider_key(provider, "nb-bad", http_client=fake.http_client()),
        ErrorCode.PROVIDER_KEY_INVALID,
    )
    assert error.status_code == 400


@pytest.mark.parametrize(
    "respond", [status(503), fail_with(httpx2.ConnectError), fail_with(httpx2.ReadTimeout)]
)
async def test_key_check_url_failure_means_unreachable(respond):
    provider = make_provider(key_check_url=CHECK_URL)
    fake = FakeProvider(respond)
    error = await assert_raises_code(
        check_provider_key(provider, "nb-key", http_client=fake.http_client()),
        ErrorCode.PROVIDER_UNREACHABLE,
    )
    assert error.status_code == 502


@pytest.mark.parametrize("code", [401, 403])
async def test_auth_failure_means_invalid_key(provider, code):
    fake = FakeProvider(status(code))
    error = await assert_raises_code(
        check_provider_key(provider, "nb-bad", http_client=fake.http_client()),
        ErrorCode.PROVIDER_KEY_INVALID,
    )
    assert error.status_code == 400


@pytest.mark.parametrize("code", [500, 502, 503])
async def test_server_error_means_unreachable(provider, code):
    fake = FakeProvider(status(code))
    error = await assert_raises_code(
        check_provider_key(provider, "nb-any", http_client=fake.http_client()),
        ErrorCode.PROVIDER_UNREACHABLE,
    )
    assert error.status_code == 502
    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    "error_class", [httpx2.ConnectTimeout, httpx2.ReadTimeout, httpx2.ConnectError]
)
async def test_timeout_or_connection_error_means_unreachable(provider, error_class):
    fake = FakeProvider(fail_with(error_class))
    await assert_raises_code(
        check_provider_key(provider, "nb-any", http_client=fake.http_client()),
        ErrorCode.PROVIDER_UNREACHABLE,
    )
    assert len(fake.requests) == 1


async def test_key_check_does_not_retry(provider):
    fake = FakeProvider(status(503))
    with pytest.raises(ApiError):
        await check_provider_key(provider, "nb-any", http_client=fake.http_client())
    assert len(fake.requests) == 1


async def test_key_check_uses_ten_second_timeout(provider, monkeypatch):
    timeouts = []
    real_make_client = providers.make_client

    def spy(*args, **kwargs):
        client = real_make_client(*args, **kwargs)
        timeouts.append(client.timeout)
        return client

    monkeypatch.setattr(providers, "make_client", spy)
    fake = FakeProvider(status(200, MODELS_OK))
    await check_provider_key(provider, "nb-good", http_client=fake.http_client())

    assert timeouts == [10.0]


async def test_check_uses_the_providers_base_url(provider):
    fake = FakeProvider(status(200, MODELS_OK))
    await check_provider_key(provider, "nb-good", http_client=fake.http_client())
    assert str(fake.requests[0].url).startswith(BASE_URL)


# --- error mapping for a saved key in use ---


def status_error(error_class, code: int, provider_url=f"{BASE_URL}chat/completions"):
    request = httpx2.Request("POST", provider_url)
    return error_class("failed", response=httpx2.Response(code, request=request), body=None)


def test_auth_failure_with_saved_key_means_rejected(provider):
    mapped = map_provider_error(
        status_error(openai.AuthenticationError, 401), provider, saved_key=True
    )
    assert mapped.code == ErrorCode.PROVIDER_KEY_REJECTED


def test_connection_failure_with_saved_key_means_unreachable(provider):
    request = httpx2.Request("POST", f"{BASE_URL}chat/completions")
    mapped = map_provider_error(
        openai.APIConnectionError(request=request), provider, saved_key=True
    )
    assert mapped.code == ErrorCode.PROVIDER_UNREACHABLE


def test_429_means_rate_limited(provider):
    mapped = map_provider_error(status_error(openai.RateLimitError, 429), provider, saved_key=True)
    assert mapped is not None
    assert mapped.code == ErrorCode.PROVIDER_RATE_LIMITED
    assert mapped.status_code == 429


def stream_error(message: str) -> openai.APIError:
    return openai.APIError(message, httpx2.Request("POST", "https://example.test/v1/chat"), body=None)


@pytest.mark.parametrize(
    "message", ["Service temporarily overloaded", "At capacity", "Rate limit exceeded"]
)
def test_a_busy_error_inside_a_stream_means_rate_limited(provider, message):
    mapped = map_provider_error(stream_error(message), provider, saved_key=True)
    assert mapped is not None
    assert mapped.code == ErrorCode.PROVIDER_RATE_LIMITED


def test_another_error_inside_a_stream_carries_the_providers_message(provider):
    mapped = map_provider_error(stream_error("Content filter triggered"), provider, saved_key=True)
    assert mapped is not None
    assert mapped.code == ErrorCode.PROVIDER_REQUEST_REFUSED
    assert mapped.message == f"{provider.label}: Content filter triggered"


def test_unmapped_client_error_carries_the_providers_message(provider):
    err = status_error(openai.BadRequestError, 400)
    mapped = map_provider_error(err, provider, saved_key=True)
    assert mapped is not None
    assert mapped.code == ErrorCode.PROVIDER_REQUEST_REFUSED
    assert provider.label in mapped.message


def test_error_messages_name_the_provider(provider):
    mapped = map_provider_error(status_error(openai.AuthenticationError, 401), provider, saved_key=True)
    assert provider.label in mapped.message


# --- loading the saved key ---


async def test_no_saved_key_means_missing(session, provider, settings_env):
    settings = Settings()
    user = await add_user(session, "user|nokey")
    await assert_raises_code(
        load_api_key(session, user, provider, settings), ErrorCode.PROVIDER_KEY_MISSING
    )


async def test_key_copied_from_another_user_means_missing(session, settings_env):
    settings = Settings()
    provider = make_provider()
    alice = await add_user(session, "user|alice")
    bob = await add_user(session, "user|bob")
    # Bob's row holds a ciphertext that was encrypted for Alice.
    await save_key(session, settings, bob, provider, "nb-alice-secret", encrypt_for=alice)

    await assert_raises_code(
        load_api_key(session, bob, provider, settings), ErrorCode.PROVIDER_KEY_MISSING
    )


async def test_keyless_provider_with_no_row_gets_a_placeholder(session, settings_env):
    settings = Settings()
    keyless = make_provider(key_required=False)
    user = await add_user(session, "user|nokeyneeded")

    api_key = await load_api_key(session, user, keyless, settings)
    assert api_key == PLACEHOLDER_KEY


async def test_client_for_uses_the_providers_base_url_and_that_users_key(session, settings_env):
    settings = Settings()
    provider = make_provider()
    alice = await add_user(session, "user|alice")
    bob = await add_user(session, "user|bob")
    await save_key(session, settings, alice, provider, "nb-alice-1111")
    await save_key(session, settings, bob, provider, "nb-bob-2222")

    for user, expected in ((alice, "nb-alice-1111"), (bob, "nb-bob-2222")):
        fake = FakeProvider(status(200, MODELS_OK))
        client = await client_for(session, user, provider, settings, http_client=fake.http_client())
        assert str(client.base_url) == BASE_URL
        await client.models.list()
        await client.close()
        assert fake.requests[0].headers["Authorization"] == f"Bearer {expected}"


async def test_another_users_key_is_never_used(session, settings_env):
    settings = Settings()
    provider = make_provider()
    alice = await add_user(session, "user|alice")
    await add_user(session, "user|bob")
    await save_key(session, settings, alice, provider, "nb-alice-only")

    bob2 = await add_user(session, "user|bob2")
    fake = FakeProvider(status(200, MODELS_OK))
    with pytest.raises(ApiError) as error:
        await client_for(session, bob2, provider, settings, http_client=fake.http_client())
    assert error.value.code == ErrorCode.PROVIDER_KEY_MISSING
    assert fake.requests == []


# --- a model the key can't use ---

MODEL = "org/some-model"


def test_404_on_a_model_call_means_model_unavailable(provider):
    mapped = map_provider_error(
        status_error(openai.NotFoundError, 404), provider, saved_key=True, model_id=MODEL
    )
    assert mapped.code == ErrorCode.MODEL_UNAVAILABLE
    assert mapped.status_code == 409
    assert MODEL in mapped.message


def test_400_saying_the_model_is_not_found_means_model_unavailable(provider):
    request = httpx2.Request("POST", f"{BASE_URL}chat/completions")
    err = openai.BadRequestError(
        f"The model `{MODEL}` does not exist",
        response=httpx2.Response(400, request=request),
        body=None,
    )
    mapped = map_provider_error(err, provider, saved_key=True, model_id=MODEL)
    assert mapped.code == ErrorCode.MODEL_UNAVAILABLE


def test_other_errors_map_as_before_with_a_model_id(provider):
    cases = [
        (status_error(openai.BadRequestError, 400), ErrorCode.PROVIDER_REQUEST_REFUSED),
        (status_error(openai.RateLimitError, 429), ErrorCode.PROVIDER_RATE_LIMITED),
        (status_error(openai.AuthenticationError, 401), ErrorCode.PROVIDER_KEY_REJECTED),
        (status_error(openai.InternalServerError, 500), ErrorCode.PROVIDER_UNREACHABLE),
    ]
    for err, code in cases:
        assert map_provider_error(err, provider, saved_key=True, model_id=MODEL).code == code


def test_404_without_a_model_id_is_a_refused_request(provider):
    mapped = map_provider_error(status_error(openai.NotFoundError, 404), provider, saved_key=True)
    assert mapped.code == ErrorCode.PROVIDER_REQUEST_REFUSED
