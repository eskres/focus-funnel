import asyncio

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import get_current_user, get_jwks_cache, get_or_create_user
from app.db import create_engine
from app.errors import register_error_handlers
from app.models import User
from tests.conftest import count_users


@pytest.fixture
def client(test_database_url, jwks_cache):
    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.get("/whoami")
    async def whoami(user: User = Depends(get_current_user)):
        return {"id": str(user.id), "auth0_sub": user.auth0_sub}

    test_app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    with TestClient(test_app) as client:
        yield client


def whoami(client, token):
    return client.get("/whoami", headers={"Authorization": f"Bearer {token}"})


def test_first_request_creates_one_user(client, test_database_url, make_token):
    response = whoami(client, make_token(sub="auth0|new-user"))

    assert response.status_code == 200
    assert response.json()["auth0_sub"] == "auth0|new-user"
    assert count_users(test_database_url, "auth0|new-user") == 1


def test_repeat_requests_reuse_the_user(client, test_database_url, make_token):
    first = whoami(client, make_token(sub="auth0|returning"))
    second = whoami(client, make_token(sub="auth0|returning"))

    assert first.json()["id"] == second.json()["id"]
    assert count_users(test_database_url, "auth0|returning") == 1


def test_different_subjects_get_different_users(client, test_database_url, make_token):
    alice = whoami(client, make_token(sub="auth0|alice")).json()
    bob = whoami(client, make_token(sub="auth0|bob")).json()

    assert alice["id"] != bob["id"]
    assert count_users(test_database_url) == 2


def test_no_user_created_without_valid_token(client, test_database_url):
    response = client.get("/whoami")

    assert response.status_code == 401
    assert count_users(test_database_url) == 0


def test_concurrent_first_requests_leave_one_user(test_database_url):
    async def run_concurrently():
        engine = create_engine(test_database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def first_request():
            async with sessions() as session:
                return await get_or_create_user(session, "auth0|racer")

        users = await asyncio.gather(*(first_request() for _ in range(5)))
        await engine.dispose()
        return users

    users = asyncio.run(run_concurrently())

    assert len({user.id for user in users}) == 1
    assert count_users(test_database_url, "auth0|racer") == 1
