import httpx2
import openai
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.nebius as nebius
from app.config import Settings
from app.crypto import encrypt_secret
from app.db import create_engine
from app.errors import ApiError, ErrorCode
from app.models import Base, NebiusApiKey, User
from app.nebius import check_api_key, client_for, load_api_key, map_nebius_error
from tests.conftest import FakeNebius, fail_with, status

BASE_URL = "https://nebius.test/v1/"
MODELS_OK = {"object": "list", "data": []}


@pytest.fixture
def settings(settings_env):
    settings_env.setenv("NEBIUS_BASE_URL", BASE_URL)
    return Settings()


@pytest.fixture
async def session():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def add_user(session, sub: str) -> User:
    user = User(auth0_sub=sub)
    session.add(user)
    await session.commit()
    return user


async def save_key(session, settings, user: User, api_key: str, encrypt_for: User | None = None):
    secret = encrypt_secret(settings.key_encryption_key, (encrypt_for or user).id, api_key)
    session.add(
        NebiusApiKey(
            user_id=user.id,
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


# --- key check against Nebius (saving a key) ---


async def test_valid_key_passes(settings):
    fake = FakeNebius(status(200, MODELS_OK))
    await check_api_key("nb-good", settings, http_client=fake.http_client())

    assert len(fake.requests) == 1
    assert str(fake.requests[0].url) == f"{BASE_URL}models"
    assert fake.requests[0].headers["Authorization"] == "Bearer nb-good"


@pytest.mark.parametrize("code", [401, 403])
async def test_auth_failure_means_invalid_key(settings, code):
    fake = FakeNebius(status(code))
    error = await assert_raises_code(
        check_api_key("nb-bad", settings, http_client=fake.http_client()),
        ErrorCode.NEBIUS_KEY_INVALID,
    )
    assert error.status_code == 400


@pytest.mark.parametrize("code", [500, 502, 503])
async def test_server_error_means_unreachable(settings, code):
    fake = FakeNebius(status(code))
    error = await assert_raises_code(
        check_api_key("nb-any", settings, http_client=fake.http_client()),
        ErrorCode.NEBIUS_UNREACHABLE,
    )
    assert error.status_code == 502
    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    "error_class", [httpx2.ConnectTimeout, httpx2.ReadTimeout, httpx2.ConnectError]
)
async def test_timeout_or_connection_error_means_unreachable(settings, error_class):
    fake = FakeNebius(fail_with(error_class))
    await assert_raises_code(
        check_api_key("nb-any", settings, http_client=fake.http_client()),
        ErrorCode.NEBIUS_UNREACHABLE,
    )
    assert len(fake.requests) == 1


async def test_key_check_does_not_retry(settings):
    fake = FakeNebius(status(503))
    with pytest.raises(ApiError):
        await check_api_key("nb-any", settings, http_client=fake.http_client())
    assert len(fake.requests) == 1


async def test_key_check_uses_ten_second_timeout(settings, monkeypatch):
    timeouts = []
    real_make_client = nebius.make_client

    def spy(*args, **kwargs):
        client = real_make_client(*args, **kwargs)
        timeouts.append(client.timeout)
        return client

    monkeypatch.setattr(nebius, "make_client", spy)
    fake = FakeNebius(status(200, MODELS_OK))
    await check_api_key("nb-good", settings, http_client=fake.http_client())

    assert timeouts == [10.0]


# --- saved key in use ---


def status_error(error_class, code: int):
    request = httpx2.Request("POST", f"{BASE_URL}chat/completions")
    return error_class("failed", response=httpx2.Response(code, request=request), body=None)


def test_auth_failure_with_saved_key_means_rejected():
    mapped = map_nebius_error(status_error(openai.AuthenticationError, 401), saved_key=True)
    assert mapped.code == ErrorCode.NEBIUS_KEY_REJECTED


def test_connection_failure_with_saved_key_means_unreachable():
    request = httpx2.Request("POST", f"{BASE_URL}chat/completions")
    mapped = map_nebius_error(openai.APIConnectionError(request=request), saved_key=True)
    assert mapped.code == ErrorCode.NEBIUS_UNREACHABLE


def test_unrelated_client_error_has_no_mapping():
    assert map_nebius_error(status_error(openai.BadRequestError, 400), saved_key=True) is None


# --- loading the saved key ---


async def test_no_saved_key_means_missing(session, settings):
    user = await add_user(session, "auth0|nokey")
    await assert_raises_code(load_api_key(session, user, settings), ErrorCode.NEBIUS_KEY_MISSING)


async def test_key_copied_from_another_user_means_missing(session, settings):
    alice = await add_user(session, "auth0|alice")
    bob = await add_user(session, "auth0|bob")
    # Bob's row holds a ciphertext that was encrypted for Alice.
    await save_key(session, settings, bob, "nb-alice-secret", encrypt_for=alice)

    await assert_raises_code(load_api_key(session, bob, settings), ErrorCode.NEBIUS_KEY_MISSING)


async def test_client_for_uses_only_that_users_key(session, settings):
    alice = await add_user(session, "auth0|alice")
    bob = await add_user(session, "auth0|bob")
    await save_key(session, settings, alice, "nb-alice-1111")
    await save_key(session, settings, bob, "nb-bob-2222")

    for user, expected in ((alice, "nb-alice-1111"), (bob, "nb-bob-2222")):
        fake = FakeNebius(status(200, MODELS_OK))
        client = await client_for(session, user, settings, http_client=fake.http_client())
        assert str(client.base_url) == BASE_URL
        await client.models.list()
        await client.close()
        assert fake.requests[0].headers["Authorization"] == f"Bearer {expected}"
