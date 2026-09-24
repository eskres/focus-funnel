import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import get_jwks_cache
from app.errors import ErrorCode
from app.main import app
from tests.conftest import count_users


@pytest.fixture
def client(test_database_url, jwks_cache):
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_me_returns_user_id_with_valid_token(client, test_database_url, make_token):
    token = make_token(sub="user|me-user")

    first = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    second = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})

    assert first.status_code == 200
    body = first.json()
    assert set(body) == {"id", "created_at"}
    uuid.UUID(body["id"])
    assert second.json()["id"] == body["id"]
    assert count_users(test_database_url, "user|me-user") == 1


def test_me_without_token_is_401(client):
    response = client.get("/api/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.UNAUTHENTICATED
