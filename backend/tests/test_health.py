from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import app


class BrokenSession:
    async def execute(self, *_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


async def broken_session():
    yield BrokenSession()


def test_health_ok_when_database_answers(settings_env):
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_needs_no_token(settings_env):
    with TestClient(app) as client:
        response = client.get("/health", headers={})
    assert response.status_code == 200


def test_health_503_when_database_fails(settings_env):
    app.dependency_overrides[get_session] = broken_session
    try:
        with TestClient(app) as client:
            response = client.get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"status": "database_unavailable"}
