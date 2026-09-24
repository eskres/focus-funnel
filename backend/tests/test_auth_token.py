"""OIDC ID token checks, with a local signing key standing in for the provider."""

import base64
import json
import time
from dataclasses import asdict

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import (
    JwksCache,
    OidcDiscovery,
    bearer_token,
    get_authenticator,
    get_jwks_cache,
    replace_origin,
)
from app.errors import ApiError, ErrorCode, register_error_handlers
from tests.conftest import TEST_ISSUER, TEST_KID, jwk_for, new_rsa_key


def make_client(jwks_cache: JwksCache) -> TestClient:
    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.get("/identity")
    async def identity(token: str = Depends(bearer_token), authenticator=Depends(get_authenticator)):
        return asdict(await authenticator.authenticate(token))

    test_app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    return TestClient(test_app)


@pytest.fixture
def client(settings_env, jwks_cache):
    return make_client(jwks_cache)


def get_identity(client, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/identity", headers=headers)


def assert_unauthenticated(response):
    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.UNAUTHENTICATED


def counting_fetch(document):
    calls = {"count": 0}

    async def fetch():
        calls["count"] += 1
        return document

    return fetch, calls


def unsigned_token(**claims) -> str:
    """A token with alg "none": a header and payload and no signature."""

    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    now = int(time.time())
    payload = {"iss": TEST_ISSUER, "aud": "focus-funnel-test-client", "sub": "x", "exp": now + 60}
    return f"{part({'alg': 'none', 'kid': TEST_KID})}.{part({**payload, **claims})}."


def test_valid_token(client, make_token):
    response = get_identity(
        client, make_token(sub="user-1", email="ana@example.org", email_verified=True)
    )
    assert response.status_code == 200
    assert response.json() == {
        "issuer": TEST_ISSUER,
        "subject": "user-1",
        "email": "ana@example.org",
        "email_verified": True,
    }


def test_audience_as_a_list_holding_the_client_id(client, make_token):
    # Pocket ID sends "aud" as a list.
    response = get_identity(client, make_token(aud=["focus-funnel-test-client"]))
    assert response.status_code == 200


def test_audience_list_without_the_client_id(client, make_token):
    assert_unauthenticated(get_identity(client, make_token(aud=["another-client"])))


def test_email_verified_must_be_true(client, make_token):
    response = get_identity(client, make_token(email="ana@example.org", email_verified="true"))
    assert response.json()["email_verified"] is False


def test_missing_token(client):
    assert_unauthenticated(get_identity(client))


def test_non_bearer_scheme(client, make_token):
    response = client.get("/identity", headers={"Authorization": f"Basic {make_token()}"})
    assert_unauthenticated(response)


def test_malformed_token(client):
    assert_unauthenticated(get_identity(client, "not-a-jwt"))


def test_expired_token(client, make_token):
    past = int(time.time()) - 3600
    assert_unauthenticated(get_identity(client, make_token(iat=past - 60, exp=past)))


def test_wrong_audience(client, make_token):
    assert_unauthenticated(get_identity(client, make_token(aud="another-client")))


def test_wrong_issuer(client, make_token):
    assert_unauthenticated(get_identity(client, make_token(iss="https://evil.example.com")))


def test_bad_signature(client, make_token):
    # Signed by a different key, but claims the provider's key id.
    assert_unauthenticated(get_identity(client, make_token(key=new_rsa_key())))


def test_missing_expiry(client, make_token):
    assert_unauthenticated(get_identity(client, make_token(exp=None)))


def test_missing_subject(client, make_token):
    assert_unauthenticated(get_identity(client, make_token(sub=None)))


def test_hs256_token_is_rejected(client, make_token):
    token = make_token(key="shared-secret-that-is-long-enough-for-hs256", algorithm="HS256")
    assert_unauthenticated(get_identity(client, token))


def test_unsigned_token_is_rejected(client):
    assert_unauthenticated(get_identity(client, unsigned_token()))


def test_algorithm_the_provider_does_not_list_is_rejected(settings_env, make_token, jwks_document):
    fetch, _ = counting_fetch(jwks_document)
    client = make_client(JwksCache(fetch, algorithms=lambda: frozenset({"ES256"})))
    assert_unauthenticated(get_identity(client, make_token()))


def test_demo_session_value_is_rejected_in_oidc_mode(client):
    assert_unauthenticated(get_identity(client, "k" * 43))


def test_unknown_key_id_triggers_refetch(settings_env, make_token, jwks_document):
    fetch, calls = counting_fetch(jwks_document)
    client = make_client(JwksCache(fetch, min_refresh_seconds=0))

    assert get_identity(client, make_token()).status_code == 200
    assert calls["count"] == 1

    # The provider rotates in a new key that the cache has not seen yet.
    rotated = new_rsa_key()
    jwks_document["keys"].append(jwk_for(rotated, "rotated-key"))

    response = get_identity(client, make_token(key=rotated, kid="rotated-key"))
    assert response.status_code == 200
    assert calls["count"] == 2

    # Known keys are served from the cache without another fetch.
    assert get_identity(client, make_token()).status_code == 200
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
        raise httpx.ConnectError("provider down")

    client = make_client(JwksCache(failing_fetch))
    response = get_identity(client, make_token())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == ErrorCode.SERVICE_UNAVAILABLE


async def test_cached_key_still_works_when_jwks_goes_down(jwks_document):
    available = True

    async def flaky_fetch():
        if not available:
            raise httpx.ConnectError("provider down")
        return jwks_document

    cache = JwksCache(flaky_fetch, min_refresh_seconds=0)
    await cache.get_signing_key(TEST_KID)

    available = False
    assert (await cache.get_signing_key(TEST_KID)).key_id == TEST_KID


# --- Discovery --------------------------------------------------------------

PUBLIC = "http://localhost:1411"
INTERNAL = "http://pocket-id:1411"


def fake_provider(jwks_document, requested: list[str], algorithms=("RS256",)):
    """A provider whose discovery document names its public origin everywhere."""

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host != "pocket-id":
            raise httpx.ConnectError("the public address is not reachable from a container")
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": PUBLIC,
                    "authorization_endpoint": f"{PUBLIC}/authorize",
                    "token_endpoint": f"{PUBLIC}/api/oidc/token",
                    "jwks_uri": f"{PUBLIC}/.well-known/jwks.json",
                    "id_token_signing_alg_values_supported": list(algorithms),
                },
            )
        if request.url.path == "/.well-known/jwks.json":
            return httpx.Response(200, json=jwks_document)
        return httpx.Response(404)

    return httpx.MockTransport(respond)


async def test_discovery_and_keys_go_through_the_internal_url(jwks_document):
    requested: list[str] = []
    discovery = OidcDiscovery(PUBLIC, INTERNAL, transport=fake_provider(jwks_document, requested))
    cache = JwksCache(discovery.fetch_jwks, algorithms=lambda: discovery.algorithms)

    key = await cache.get_signing_key(TEST_KID)

    assert key.key_id == TEST_KID
    assert requested == [
        f"{INTERNAL}/.well-known/openid-configuration",
        f"{INTERNAL}/.well-known/jwks.json",
    ]
    assert cache.algorithms == frozenset({"RS256"})


async def test_without_internal_url_the_public_address_is_used(jwks_document):
    requested: list[str] = []
    discovery = OidcDiscovery(PUBLIC, None, transport=fake_provider(jwks_document, requested))

    with pytest.raises(httpx.ConnectError):
        await discovery.fetch_jwks()
    assert requested == [f"{PUBLIC}/.well-known/openid-configuration"]


async def test_discovery_algorithms_are_intersected_with_asymmetric_ones(jwks_document):
    discovery = OidcDiscovery(
        PUBLIC, INTERNAL, transport=fake_provider(jwks_document, [], ("HS256", "RS256"))
    )
    cache = JwksCache(discovery.fetch_jwks, algorithms=lambda: discovery.algorithms)
    await cache.get_signing_key(TEST_KID)
    assert cache.algorithms == frozenset({"RS256"})


def test_end_to_end_with_discovery_through_the_internal_url(settings_env, make_token, jwks_document):
    settings_env.setenv("OIDC_ISSUER", PUBLIC)
    settings_env.setenv("OIDC_INTERNAL_URL", INTERNAL)
    discovery = OidcDiscovery(PUBLIC, INTERNAL, transport=fake_provider(jwks_document, []))
    client = make_client(JwksCache(discovery.fetch_jwks, algorithms=lambda: discovery.algorithms))

    # "iss" is still checked against OIDC_ISSUER, the public address.
    assert get_identity(client, make_token(iss=PUBLIC)).status_code == 200
    assert_unauthenticated(get_identity(client, make_token(iss=INTERNAL)))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{PUBLIC}/.well-known/jwks.json", f"{INTERNAL}/.well-known/jwks.json"),
        (f"{PUBLIC}/api/oidc/token?x=1", f"{INTERNAL}/api/oidc/token?x=1"),
        ("https://other.example/keys", "https://other.example/keys"),
    ],
)
def test_replace_origin(url, expected):
    assert replace_origin(url, PUBLIC, INTERNAL) == expected


def test_replace_origin_keeps_an_issuer_path():
    issuer = "https://sso.example.org/realms/home"
    assert (
        replace_origin(f"{issuer}/protocol/openid-connect/certs", issuer, "http://keycloak:8080")
        == "http://keycloak:8080/realms/home/protocol/openid-connect/certs"
    )
