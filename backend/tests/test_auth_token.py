import time

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import JwksCache, get_jwks_cache, get_token_claims
from app.errors import ApiError, ErrorCode, register_error_handlers
from tests.conftest import TEST_KID, jwk_for, new_rsa_key


def make_client(jwks_cache: JwksCache) -> TestClient:
    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.get("/claims")
    async def claims(token_claims: dict = Depends(get_token_claims)):
        return {"sub": token_claims["sub"]}

    test_app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    return TestClient(test_app)


@pytest.fixture
def client(settings_env, jwks_cache):
    return make_client(jwks_cache)


def get_claims(client, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/claims", headers=headers)


def assert_unauthenticated(response):
    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.UNAUTHENTICATED


def counting_fetch(document):
    calls = {"count": 0}

    async def fetch():
        calls["count"] += 1
        return document

    return fetch, calls


def test_valid_token(client, make_token):
    response = get_claims(client, make_token(sub="auth0|alice"))
    assert response.status_code == 200
    assert response.json() == {"sub": "auth0|alice"}


def test_missing_token(client):
    assert_unauthenticated(get_claims(client))


def test_non_bearer_scheme(client, make_token):
    response = client.get("/claims", headers={"Authorization": f"Basic {make_token()}"})
    assert_unauthenticated(response)


def test_malformed_token(client):
    assert_unauthenticated(get_claims(client, "not-a-jwt"))


def test_expired_token(client, make_token):
    past = int(time.time()) - 3600
    assert_unauthenticated(get_claims(client, make_token(iat=past - 60, exp=past)))


def test_wrong_audience(client, make_token):
    assert_unauthenticated(get_claims(client, make_token(aud="https://other-api")))


def test_wrong_issuer(client, make_token):
    assert_unauthenticated(get_claims(client, make_token(iss="https://evil.example.com/")))


def test_bad_signature(client, make_token):
    # Signed by a different key, but claims the tenant's key id.
    assert_unauthenticated(get_claims(client, make_token(key=new_rsa_key())))


def test_missing_expiry(client, make_token):
    assert_unauthenticated(get_claims(client, make_token(exp=None)))


def test_missing_subject(client, make_token):
    assert_unauthenticated(get_claims(client, make_token(sub=None)))


def test_hs256_token_is_rejected(client, make_token):
    token = make_token(key="shared-secret-that-is-long-enough-for-hs256", algorithm="HS256")
    assert_unauthenticated(get_claims(client, token))


def test_unknown_key_id_triggers_refetch(settings_env, make_token, jwks_document):
    fetch, calls = counting_fetch(jwks_document)
    client = make_client(JwksCache(fetch, min_refresh_seconds=0))

    assert get_claims(client, make_token()).status_code == 200
    assert calls["count"] == 1

    # Auth0 rotates in a new key that the cache has not seen yet.
    rotated = new_rsa_key()
    jwks_document["keys"].append(jwk_for(rotated, "rotated-key"))

    response = get_claims(client, make_token(key=rotated, kid="rotated-key"))
    assert response.status_code == 200
    assert calls["count"] == 2

    # Known keys are served from the cache without another fetch.
    assert get_claims(client, make_token()).status_code == 200
    assert calls["count"] == 2


async def test_refetch_is_rate_limited(jwks_document):
    fetch, calls = counting_fetch(jwks_document)
    now = [1000.0]
    cache = JwksCache(fetch, min_refresh_seconds=60, clock=lambda: now[0])

    for _ in range(3):
        with pytest.raises(ApiError) as error:
            await cache.get_signing_key("unknown")
        assert error.value.status_code == 401
    assert calls["count"] == 1

    now[0] += 61
    with pytest.raises(ApiError):
        await cache.get_signing_key("unknown")
    assert calls["count"] == 2


def test_jwks_unavailable_without_cached_key_returns_503(settings_env, make_token):
    async def failing_fetch():
        raise httpx.ConnectError("auth0 down")

    client = make_client(JwksCache(failing_fetch))
    response = get_claims(client, make_token())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == ErrorCode.SERVICE_UNAVAILABLE


async def test_cached_key_still_works_when_jwks_goes_down(jwks_document):
    available = True

    async def flaky_fetch():
        if not available:
            raise httpx.ConnectError("auth0 down")
        return jwks_document

    cache = JwksCache(flaky_fetch, min_refresh_seconds=0)
    await cache.get_signing_key(TEST_KID)

    available = False
    assert (await cache.get_signing_key(TEST_KID)).key_id == TEST_KID
