import asyncio
import base64
import os
import time
import uuid

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select
from sqlalchemy.pool import NullPool

from app.auth import JwksCache
from app.chat.config import get_chat_config
from app.chat.model_info import clear_model_info_cache
from app.config import get_settings
from app.db import create_engine, get_engine, get_sessionmaker
from app.models import Base, User
from app.provider_config import get_providers_config

pytest_plugins = ["tests.chat_helpers"]

REQUIRED_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "AUTH0_DOMAIN": "test-tenant.example.com",
    "AUTH0_AUDIENCE": "https://api.focus-funnel.test",
}
TEST_ISSUER = f"https://{REQUIRED_ENV['AUTH0_DOMAIN']}/"
TEST_KID = "test-key-1"


CACHED = (get_settings, get_engine, get_sessionmaker, get_providers_config, get_chat_config)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    for cached in CACHED:
        cached.cache_clear()
    clear_model_info_cache()
    yield
    for cached in CACHED:
        cached.cache_clear()
    clear_model_info_cache()


@pytest.fixture
def settings_env(monkeypatch):
    """Set a complete, valid backend environment."""
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("KEY_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    return monkeypatch


@pytest.fixture
def test_database_url(tmp_path, settings_env) -> str:
    """A database with fresh tables, used as DATABASE_URL for the app.

    Set TEST_DATABASE_URL to run the same tests against Postgres. The engine
    here doesn't pool connections, because TestClient runs its own event loop.
    """
    url = os.environ.get("TEST_DATABASE_URL") or (
        f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}"
    )

    async def reset_tables():
        engine = create_engine(url, poolclass=NullPool)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(reset_tables())
    settings_env.setenv("DATABASE_URL", url)
    return url


def count_users(url: str, auth0_sub: str | None = None) -> int:
    async def count():
        engine = create_engine(url, poolclass=NullPool)
        query = select(func.count()).select_from(User)
        if auth0_sub is not None:
            query = query.where(User.auth0_sub == auth0_sub)
        async with engine.connect() as connection:
            result = (await connection.execute(query)).scalar_one()
        await engine.dispose()
        return result

    return asyncio.run(count())


class FakeProvider:
    """Records requests and answers them through an httpx2 mock transport."""

    def __init__(self, respond):
        self.requests: list[httpx2.Request] = []
        self._respond = respond

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._respond(request)

    def http_client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle))


def status(code: int, json=None):
    return lambda _request: httpx2.Response(code, json=json if json is not None else {})


def fail_with(error_class):
    def respond(request):
        raise error_class("network failure", request=request)

    return respond


def new_rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_for(private_key: rsa.RSAPrivateKey, kid: str) -> dict:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


@pytest.fixture(scope="session")
def signing_key() -> rsa.RSAPrivateKey:
    return new_rsa_key()


@pytest.fixture
def jwks_document(signing_key) -> dict:
    """The JWKS the fake Auth0 tenant serves. Tests may change its "keys" list."""
    return {"keys": [jwk_for(signing_key, TEST_KID)]}


@pytest.fixture
def jwks_cache(jwks_document) -> JwksCache:
    async def fetch():
        return jwks_document

    return JwksCache(fetch)


@pytest.fixture
def make_token(signing_key):
    """Build a signed access token; keyword arguments override claims."""

    def build(key=None, kid=TEST_KID, algorithm="RS256", **claims) -> str:
        now = int(time.time())
        payload = {
            "iss": TEST_ISSUER,
            "aud": REQUIRED_ENV["AUTH0_AUDIENCE"],
            "sub": f"auth0|{uuid.uuid4().hex}",
            "iat": now,
            "exp": now + 3600,
            **claims,
        }
        payload = {name: value for name, value in payload.items() if value is not None}
        return jwt.encode(
            payload, key or signing_key, algorithm=algorithm, headers={"kid": kid}
        )

    return build
