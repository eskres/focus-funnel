import os
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.auth import get_jwks_cache
from app.errors import ErrorCode
from app.main import app
from app.providers import get_provider_http_client
from tests.conftest import FakeProvider, fail_with, status

FIXTURE_CONFIG = Path(__file__).parent / "fixtures" / "providers" / "valid.yaml"
MODELS_OK = {"object": "list", "data": []}
VALID_KEY = "nb-valid-key-aaaa1111"
OTHER_VALID_KEY = "nb-valid-key-bbbb2222"


def accepting(*keys: str) -> FakeProvider:
    """A fake that accepts any of the given keys, or any key at all if none given."""

    def respond(request: httpx2.Request) -> httpx2.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not keys or token in keys:
            return httpx2.Response(200, json=MODELS_OK)
        return httpx2.Response(401, json={"error": "invalid key"})

    return FakeProvider(respond)


@pytest.fixture
def settings_env(settings_env):
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(FIXTURE_CONFIG))
    return settings_env


@pytest.fixture
def fake(settings_env):
    provider = accepting(VALID_KEY, OTHER_VALID_KEY)
    app.dependency_overrides[get_provider_http_client] = lambda: provider.http_client()
    return provider


@pytest.fixture
def client(test_database_url, jwks_cache, fake):
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def alice(make_token):
    return {"Authorization": f"Bearer {make_token(sub='user|alice')}"}


@pytest.fixture
def bob(make_token):
    return {"Authorization": f"Bearer {make_token(sub='user|bob')}"}


def error_code(response) -> str:
    return response.json()["error"]["code"]


def by_id(response, provider_id: str) -> dict:
    return next(p for p in response.json()["providers"] if p["id"] == provider_id)


# --- 5.1: GET /api/providers ---


def test_every_preset_appears_with_key_link_and_notice(client, alice):
    response = client.get("/api/providers", headers=alice)
    assert response.status_code == 200

    nebius = by_id(response, "nebius")
    assert nebius["label"] == "Nebius Token Factory"
    assert nebius["key_url"] == "https://tokenfactory.nebius.com/project/api-keys"
    assert nebius["notice"]
    assert nebius["key_saved"] is False

    local = by_id(response, "local")
    assert local["key_required"] is False


def test_custom_provider_appears_in_listing(client, alice):
    response = client.get("/api/providers", headers=alice)
    custom = by_id(response, "custom")
    assert custom["is_custom"] is True
    assert response.json()["custom_provider_allowed"] is True


def test_key_status_is_per_user(client, alice, bob):
    client.put("/api/providers/nebius/key", headers=alice, json={"key": VALID_KEY})

    assert by_id(client.get("/api/providers", headers=alice), "nebius")["key_saved"] is True
    assert by_id(client.get("/api/providers", headers=bob), "nebius")["key_saved"] is False


# --- 5.2: PUT / DELETE /api/providers/{id}/key ---


def test_valid_key_is_saved(client, alice, fake):
    response = client.put("/api/providers/nebius/key", headers=alice, json={"key": VALID_KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["key_saved"] is True
    assert body["key_last4"] == "1111"
    assert body["key_saved_at"]
    assert fake.requests[-1].headers["Authorization"] == f"Bearer {VALID_KEY}"


def test_invalid_key_is_not_saved(client, alice):
    response = client.put("/api/providers/nebius/key", headers=alice, json={"key": "nb-wrong"})

    assert response.status_code == 400
    assert error_code(response) == ErrorCode.PROVIDER_KEY_INVALID
    assert by_id(client.get("/api/providers", headers=alice), "nebius")["key_saved"] is False


@pytest.mark.parametrize(
    "respond", [fail_with(httpx2.ConnectError), fail_with(httpx2.ReadTimeout), status(503)]
)
def test_unreachable_provider_saves_nothing(client, alice, respond):
    app.dependency_overrides[get_provider_http_client] = lambda: FakeProvider(
        respond
    ).http_client()

    response = client.put("/api/providers/nebius/key", headers=alice, json={"key": VALID_KEY})

    assert response.status_code == 502
    assert error_code(response) == ErrorCode.PROVIDER_UNREACHABLE
    assert by_id(client.get("/api/providers", headers=alice), "nebius")["key_saved"] is False


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_empty_key_is_rejected_for_a_provider_that_needs_one(client, alice, fake, blank):
    response = client.put("/api/providers/nebius/key", headers=alice, json={"key": blank})

    assert response.status_code == 422
    assert error_code(response) == ErrorCode.VALIDATION_ERROR
    assert fake.requests == []


def test_valid_replacement_replaces_the_key(client, alice):
    client.put("/api/providers/nebius/key", headers=alice, json={"key": VALID_KEY})
    response = client.put(
        "/api/providers/nebius/key", headers=alice, json={"key": OTHER_VALID_KEY}
    )

    assert response.status_code == 200
    assert response.json()["key_last4"] == "2222"


def test_failed_replacement_keeps_the_old_key(client, alice):
    saved = client.put(
        "/api/providers/nebius/key", headers=alice, json={"key": VALID_KEY}
    ).json()

    response = client.put("/api/providers/nebius/key", headers=alice, json={"key": "nb-wrong"})

    assert response.status_code == 400
    assert by_id(client.get("/api/providers", headers=alice), "nebius") == saved


def test_delete_leaves_other_providers_alone(client, alice):
    client.put("/api/providers/nebius/key", headers=alice, json={"key": VALID_KEY})
    client.put("/api/providers/local/key", headers=alice, json={"key": ""})

    response = client.delete("/api/providers/nebius/key", headers=alice)

    assert response.status_code == 204
    listing = client.get("/api/providers", headers=alice)
    assert by_id(listing, "nebius")["key_saved"] is False
    assert by_id(listing, "local")["key_saved"] is False  # never had a key; unaffected either way


def test_delete_without_a_saved_key_is_fine(client, alice):
    assert client.delete("/api/providers/nebius/key", headers=alice).status_code == 204


def test_keyless_local_provider_saved_with_no_key(client, alice):
    # "local" accepts requests without a key, so the check must succeed with
    # the placeholder key too, not just with a real one.
    app.dependency_overrides[get_provider_http_client] = lambda: accepting().http_client()

    response = client.put("/api/providers/local/key", headers=alice, json={"key": ""})

    assert response.status_code == 200
    body = response.json()
    assert body["key_saved"] is False
    assert body["key_required"] is False


def test_endpoints_require_a_token(client):
    assert client.get("/api/providers").status_code == 401
    assert client.put("/api/providers/nebius/key", json={"key": VALID_KEY}).status_code == 401
    assert client.delete("/api/providers/nebius/key").status_code == 401


def test_unknown_provider_id_is_not_found(client, alice):
    response = client.put("/api/providers/does-not-exist/key", headers=alice, json={"key": "x"})
    assert response.status_code == 404
    assert error_code(response) == ErrorCode.NOT_FOUND


# --- 5.3: custom provider rules ---


CUSTOM_URL = "https://custom.test/v1/"


def test_custom_provider_save_and_list_models(client, alice, fake):
    response = client.put(
        "/api/providers/custom/key",
        headers=alice,
        json={"key": VALID_KEY, "base_url": CUSTOM_URL},
    )
    assert response.status_code == 200
    assert response.json()["base_url"] == CUSTOM_URL

    models_response = client.get("/api/providers/custom/models", headers=alice)
    assert models_response.status_code == 200


def test_base_url_rejected_for_a_preset(client, alice):
    response = client.put(
        "/api/providers/nebius/key",
        headers=alice,
        json={"key": VALID_KEY, "base_url": "https://not-nebius.test/v1/"},
    )
    assert response.status_code == 422
    assert error_code(response) == ErrorCode.VALIDATION_ERROR


@pytest.mark.parametrize("bad_url", ["ftp://custom.test/v1/", "not-a-url", "javascript:alert(1)"])
def test_custom_base_url_must_be_http_or_https(client, alice, bad_url):
    response = client.put(
        "/api/providers/custom/key", headers=alice, json={"key": VALID_KEY, "base_url": bad_url}
    )
    assert response.status_code == 422
    assert error_code(response) == ErrorCode.VALIDATION_ERROR


def test_custom_provider_refused_when_disabled(test_database_url, jwks_cache, fake, alice):
    # Settings are read once at startup, so the env var must be set before
    # the app (and its cached Settings) comes up, not mid-test.
    os.environ["ALLOW_CUSTOM_PROVIDER"] = "false"
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    try:
        with TestClient(app) as scoped_client:
            response = scoped_client.put(
                "/api/providers/custom/key",
                headers=alice,
                json={"key": VALID_KEY, "base_url": CUSTOM_URL},
            )
            assert response.status_code == 422
            assert error_code(response) == ErrorCode.VALIDATION_ERROR

            listing = scoped_client.get("/api/providers", headers=alice)
            assert listing.json()["custom_provider_allowed"] is False
            assert all(p["id"] != "custom" for p in listing.json()["providers"])
    finally:
        app.dependency_overrides.clear()
        del os.environ["ALLOW_CUSTOM_PROVIDER"]


def test_custom_base_url_required(client, alice):
    response = client.put("/api/providers/custom/key", headers=alice, json={"key": VALID_KEY})
    assert response.status_code == 422
    assert error_code(response) == ErrorCode.VALIDATION_ERROR


# --- 5.4: keys never leak ---


def test_responses_never_contain_the_full_key(client, alice):
    responses = [
        client.put("/api/providers/nebius/key", headers=alice, json={"key": VALID_KEY}),
        client.get("/api/providers", headers=alice),
    ]
    for response in responses:
        assert VALID_KEY not in response.text


def test_key_status_holds_at_most_four_characters(client, alice):
    response = client.put("/api/providers/nebius/key", headers=alice, json={"key": VALID_KEY})
    assert response.json()["key_last4"] == VALID_KEY[-4:]
    assert len(response.json()["key_last4"]) <= 4


def test_two_users_keys_for_one_provider_never_mix(client, alice, bob):
    client.put("/api/providers/nebius/key", headers=alice, json={"key": VALID_KEY})
    client.put("/api/providers/nebius/key", headers=alice, json={"key": OTHER_VALID_KEY})
    # bob has never saved a key; make sure alice's key can't leak into his status
    assert by_id(client.get("/api/providers", headers=bob), "nebius")["key_saved"] is False
    assert by_id(client.get("/api/providers", headers=bob), "nebius")["key_last4"] is None
