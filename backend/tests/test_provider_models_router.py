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
VALID_KEY = "nb-valid-key-aaaa1111"

VERBOSE_MODELS = {
    "object": "list",
    "data": [
        {
            "id": "org/model-with-everything",
            "context_length": 131072,
            "pricing": {"prompt": "0.0000002", "completion": "0.0000006"},
            "supported_features": ["tools", "json_mode"],
        },
        {
            "id": "org/model-reports-nothing",
        },
    ],
}


@pytest.fixture
def settings_env(settings_env):
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(FIXTURE_CONFIG))
    return settings_env


@pytest.fixture
def client(test_database_url, jwks_cache, settings_env):
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def alice(make_token):
    return {"Authorization": f"Bearer {make_token(sub='auth0|alice')}"}


@pytest.fixture
def bob(make_token):
    return {"Authorization": f"Bearer {make_token(sub='auth0|bob')}"}


def save_key(client, headers, key=VALID_KEY, provider="nebius"):
    return client.put(f"/api/providers/{provider}/key", headers=headers, json={"key": key})


def error_code(response) -> str:
    return response.json()["error"]["code"]


def test_prices_and_context_length_returned_when_reported(client, alice):
    fake = FakeProvider(status(200, VERBOSE_MODELS))
    app.dependency_overrides[get_provider_http_client] = lambda: fake.http_client()
    save_key(client, alice)

    response = client.get("/api/providers/nebius/models", headers=alice)
    assert response.status_code == 200
    models = {m["id"]: m for m in response.json()["models"]}

    full = models["org/model-with-everything"]
    assert full["context_length"] == 131072
    assert full["prices"] == {"prompt": "0.0000002", "completion": "0.0000006"}
    assert full["features"]["tool_calling"] == "supported"

    bare = models["org/model-reports-nothing"]
    assert bare["context_length"] is None
    assert bare["prices"] is None
    assert bare["features"]["tool_calling"] == "unknown"


def test_fields_absent_when_provider_does_not_report_them(client, alice):
    """The 'local' preset in the fixture reports no prices/context/features."""
    fake = FakeProvider(
        status(200, {"object": "list", "data": [{"id": "some-model"}]})
    )
    app.dependency_overrides[get_provider_http_client] = lambda: fake.http_client()
    save_key(client, alice, key="", provider="local")

    response = client.get("/api/providers/local/models", headers=alice)
    assert response.status_code == 200
    model = response.json()["models"][0]
    assert model["context_length"] is None
    assert model["prices"] is None
    assert model["features"]["tool_calling"] == "unknown"


def test_missing_key_gives_provider_key_missing(client, alice):
    response = client.get("/api/providers/nebius/models", headers=alice)
    assert response.status_code == 409
    assert error_code(response) == ErrorCode.PROVIDER_KEY_MISSING


def test_rejected_key_gives_provider_key_rejected(client, alice):
    fake = FakeProvider(status(200, {"object": "list", "data": []}))
    app.dependency_overrides[get_provider_http_client] = lambda: fake.http_client()
    save_key(client, alice)

    app.dependency_overrides[get_provider_http_client] = lambda: FakeProvider(
        status(401)
    ).http_client()
    response = client.get("/api/providers/nebius/models", headers=alice)
    assert response.status_code == 409
    assert error_code(response) == ErrorCode.PROVIDER_KEY_REJECTED


@pytest.mark.parametrize(
    "respond", [fail_with(httpx2.ConnectError), fail_with(httpx2.ReadTimeout), status(503)]
)
def test_unreachable_provider_gives_no_partial_list(client, alice, respond):
    fake = FakeProvider(status(200, {"object": "list", "data": []}))
    app.dependency_overrides[get_provider_http_client] = lambda: fake.http_client()
    save_key(client, alice)

    app.dependency_overrides[get_provider_http_client] = lambda: FakeProvider(
        respond
    ).http_client()
    response = client.get("/api/providers/nebius/models", headers=alice)
    assert response.status_code == 502
    assert error_code(response) == ErrorCode.PROVIDER_UNREACHABLE
    assert "models" not in response.json()


def test_two_users_lists_use_their_own_keys(client, alice, bob):
    def respond_for(accepted_key):
        def respond(request):
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            if token == accepted_key:
                return httpx2.Response(
                    200,
                    json={"object": "list", "data": [{"id": f"model-for-{accepted_key}"}]},
                )
            return httpx2.Response(401, json={})

        return respond

    app.dependency_overrides[get_provider_http_client] = lambda: FakeProvider(
        respond_for("alice-key")
    ).http_client()
    save_key(client, alice, key="alice-key")

    app.dependency_overrides[get_provider_http_client] = lambda: FakeProvider(
        respond_for("bob-key")
    ).http_client()
    save_key(client, bob, key="bob-key")

    # Both users' saved keys are checked against whichever fake transport is
    # wired up at request time, so use one fake that answers to either key -
    # each request must still only ever send that one user's own key.
    def respond_either(request):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token in ("alice-key", "bob-key"):
            return httpx2.Response(
                200, json={"object": "list", "data": [{"id": f"model-for-{token}"}]}
            )
        return httpx2.Response(401, json={})

    app.dependency_overrides[get_provider_http_client] = lambda: FakeProvider(
        respond_either
    ).http_client()

    alice_models = client.get("/api/providers/nebius/models", headers=alice)
    assert [m["id"] for m in alice_models.json()["models"]] == ["model-for-alice-key"]

    bob_models = client.get("/api/providers/nebius/models", headers=bob)
    assert [m["id"] for m in bob_models.json()["models"]] == ["model-for-bob-key"]
