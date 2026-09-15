import httpx2
import pytest
from fastapi.testclient import TestClient

from app.auth import get_jwks_cache
from app.errors import ErrorCode
from app.main import app
from app.nebius import get_nebius_http_client
from tests.conftest import FakeNebius, fail_with, status

VALID_KEY = "nb-valid-key-aaaa1111"
OTHER_VALID_KEY = "nb-valid-key-bbbb2222"
MODELS_OK = {"object": "list", "data": []}
URL = "/api/settings/api-key"


def nebius_accepting(*accepted_keys: str) -> FakeNebius:
    def respond(request: httpx2.Request) -> httpx2.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token in accepted_keys:
            return httpx2.Response(200, json=MODELS_OK)
        return httpx2.Response(401, json={"error": "invalid key"})

    return FakeNebius(respond)


@pytest.fixture
def nebius(settings_env):
    settings_env.setenv("NEBIUS_BASE_URL", "https://nebius.test/v1/")
    fake = nebius_accepting(VALID_KEY, OTHER_VALID_KEY)
    app.dependency_overrides[get_nebius_http_client] = lambda: fake.http_client()
    return fake


@pytest.fixture
def client(test_database_url, jwks_cache, nebius):
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


def error_code(response) -> str:
    return response.json()["error"]["code"]


def test_no_key_saved(client, alice):
    response = client.get(URL, headers=alice)
    assert response.status_code == 200
    assert response.json() == {"saved": False}


def test_valid_key_is_saved(client, alice, nebius):
    response = client.put(URL, headers=alice, json={"api_key": VALID_KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["last4"] == "1111"
    assert body["saved_at"]
    assert client.get(URL, headers=alice).json() == body
    assert nebius.requests[-1].headers["Authorization"] == f"Bearer {VALID_KEY}"


def test_key_is_stripped_before_check_and_save(client, alice):
    response = client.put(URL, headers=alice, json={"api_key": f"  {VALID_KEY}\n"})
    assert response.status_code == 200
    assert response.json()["last4"] == "1111"


def test_invalid_key_is_not_saved(client, alice):
    response = client.put(URL, headers=alice, json={"api_key": "nb-wrong-key"})

    assert response.status_code == 400
    assert error_code(response) == ErrorCode.NEBIUS_KEY_INVALID
    assert "rejected" in response.json()["error"]["message"]
    assert client.get(URL, headers=alice).json() == {"saved": False}


@pytest.mark.parametrize(
    "respond", [fail_with(httpx2.ConnectError), fail_with(httpx2.ReadTimeout), status(503)]
)
def test_unreachable_nebius_saves_nothing(client, alice, respond):
    fake = FakeNebius(respond)
    app.dependency_overrides[get_nebius_http_client] = lambda: fake.http_client()

    response = client.put(URL, headers=alice, json={"api_key": VALID_KEY})

    assert response.status_code == 502
    assert error_code(response) == ErrorCode.NEBIUS_UNREACHABLE
    assert "try again" in response.json()["error"]["message"].lower()
    assert client.get(URL, headers=alice).json() == {"saved": False}


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_empty_key_is_rejected_without_calling_nebius(client, alice, nebius, blank):
    response = client.put(URL, headers=alice, json={"api_key": blank})

    assert response.status_code == 422
    assert error_code(response) == ErrorCode.VALIDATION_ERROR
    assert nebius.requests == []
    assert client.get(URL, headers=alice).json() == {"saved": False}


def test_valid_replacement_replaces_the_key(client, alice):
    client.put(URL, headers=alice, json={"api_key": VALID_KEY})
    response = client.put(URL, headers=alice, json={"api_key": OTHER_VALID_KEY})

    assert response.status_code == 200
    assert response.json()["last4"] == "2222"
    assert client.get(URL, headers=alice).json()["last4"] == "2222"


def test_invalid_replacement_keeps_the_old_key(client, alice):
    saved = client.put(URL, headers=alice, json={"api_key": VALID_KEY}).json()

    response = client.put(URL, headers=alice, json={"api_key": "nb-wrong-key"})

    assert response.status_code == 400
    assert error_code(response) == ErrorCode.NEBIUS_KEY_INVALID
    assert client.get(URL, headers=alice).json() == saved


def test_delete_removes_the_key(client, alice):
    client.put(URL, headers=alice, json={"api_key": VALID_KEY})

    response = client.delete(URL, headers=alice)

    assert response.status_code == 204
    assert client.get(URL, headers=alice).json() == {"saved": False}


def test_delete_without_saved_key_is_fine(client, alice):
    assert client.delete(URL, headers=alice).status_code == 204


def test_responses_never_contain_the_full_key(client, alice):
    responses = [
        client.put(URL, headers=alice, json={"api_key": VALID_KEY}),
        client.get(URL, headers=alice),
    ]
    for response in responses:
        assert VALID_KEY not in response.text
        assert set(response.json()) <= {"saved", "last4", "saved_at"}


def test_invalid_key_error_does_not_echo_the_key(client, alice):
    response = client.put(URL, headers=alice, json={"api_key": "nb-wrong-key"})
    assert "nb-wrong-key" not in response.text


def test_endpoints_require_a_token(client):
    assert client.get(URL).status_code == 401
    assert client.put(URL, json={"api_key": VALID_KEY}).status_code == 401
    assert client.delete(URL).status_code == 401


def test_users_see_only_their_own_key(client, alice, bob):
    client.put(URL, headers=alice, json={"api_key": VALID_KEY})

    assert client.get(URL, headers=bob).json() == {"saved": False}
    client.delete(URL, headers=bob)
    assert client.get(URL, headers=alice).json()["saved"] is True
